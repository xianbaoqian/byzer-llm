from http import HTTPStatus
from typing import List, Dict
import dashscope
from dashscope.api_entities.dashscope_response import Message
import time
import ray
from byzerllm.utils import VLLMStreamServer
import threading
import asyncio



class CustomSaasAPI:
    def __init__(self, infer_params: Dict[str, str]) -> None:
        self.api_key: str = infer_params["saas.api_key"]  
        self.model = infer_params.get("saas.model", "qwen-turbo") 
        try:
            ray.get_actor("VLLM_STREAM_SERVER")
        except ValueError:            
            ray.remote(VLLMStreamServer).options(name="VLLM_STREAM_SERVER",lifetime="detached",max_concurrency=1000).remote()     

     # saas/proprietary
    def get_meta(self):
        return [{
            "model_deploy_type": "saas",
            "backend":"saas",
            "support_stream": True
        }]  


    async def async_stream_chat(
            self,
            tokenizer,
            ins: str,
            his: List[dict] = [],
            max_length: int = 1024,
            top_p: float = 0.9,
            temperature: float = 0.1,
            **kwargs
    ):
        
        messages = his + [{"role": "user", "content": ins}]        
        
        start_time = time.monotonic()

        other_params = {}
                
        if "top_k" in kwargs:
            other_params["top_k"] = int(kwargs["top_k"])

        if "stop" in kwargs:
            other_params["stop"] = kwargs["stop"]

        if "enable_search" in kwargs:
            other_params["enable_search"] = kwargs["enable_search"]        

        if "enable_search_enhance" in kwargs:
            other_params["enable_search_enhance"] = kwargs["enable_search_enhance"]

        if "stream" in kwargs:        
            other_params["stream"] = kwargs["stream"]

        if "incremental_output" in kwargs:
            other_params["incremental_output"] = kwargs["incremental_output"]    

        stream = kwargs.get("stream",False)    
        
        res_data = dashscope.Generation.call(model = self.model,
                                            messages=[Message(**message) for message in messages],
                                            api_key=self.api_key,
                                            max_tokens=max_length,
                                            temperature=temperature,
                                            top_p=top_p,
                                            result_format='message',**other_params)
        
        if stream:
            print("streaming mode",flush=True)
            server = ray.get_actor("VLLM_STREAM_SERVER")
            request_id = None

            async def writer(): 
                for response in res_data:
                    print(response.status_code)
                    if response.status_code == HTTPStatus.OK:
                        v = response.output.choices[0]['message']['content']
                        request_id = response.request_id
                        print(f"async chat:{request_id}",flush=True)
                        await server.add_item.remote(response.request_id, v)
                        
                    else:
                        print('Request id: %s, Status code: %s, error code: %s, error message: %s' % (
                            response.request_id, response.status_code,
                            response.code, response.message
                        ),flush=True) 
                await server.mark_done.remote(request_id)

            asyncio.create_task(writer())
                               
            time_count= 10*100
            while request_id is None and time_count > 0:
                time.sleep(0.01)
                time_count -= 1
            
            if request_id is None:
                raise Exception("Failed to get request id")
            
            await server.add_item.remote(request_id, "RUNNING")             
            return [("",{"metadata":{"request_id":request_id}})]  
              
        time_cost = time.monotonic() - start_time
        
        if res_data["status_code"] == HTTPStatus.OK:
             generated_text = res_data["output"]["choices"][0]["message"]["content"]
             generated_tokens_count = res_data["usage"]["output_tokens"]
             input_tokens_count = res_data["usage"]["input_tokens"]

             return [(generated_text,{"metadata":{
                        "request_id":res_data["request_id"],
                        "input_tokens_count":input_tokens_count,
                        "generated_tokens_count":generated_tokens_count,
                        "time_cost":time_cost,
                        "first_token_time":0,
                        "speed":float(generated_tokens_count)/time_cost,        
                    }})] 
        else:
            s = 'Request id: %s, Status code: %s, error code: %s, error message: %s' % (
                res_data.request_id, res_data.status_code,
                res_data.code, res_data.message
            )
            print(s)
            raise Exception(s)

    
        

