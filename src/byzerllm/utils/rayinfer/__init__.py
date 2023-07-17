import ray
from ray import serve
from aviary.backend.server.run import llm_server,LLMApp 
import ray._private.usage.usage_lib
from typing import Union
import socket
import os
import base64

def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def _build_yaml(
        model_dir:str,
        num_gpus_per_worker:int=1,
):
    model_id = base64.b64encode(model_dir.encode("utf-8")).decode("utf-8").replace("=","")
    template = f"""deployment_config:
  max_concurrent_queries: 64  
  ray_actor_options:
      resources:
        accelerator_type_cpu: 0.01  
model_config:
  batching: static
  model_id: {model_id}
  model_url: {model_dir}
  max_input_words: 800
  initialization:    
    initializer:
      type: DeepSpeed
    dtype: float16
      from_pretrained_kwargs:
        use_cache: true
      use_kernel: true
      max_tokens: 1536  
    pipeline: transformers
  generation:
    max_input_words: 800
    max_batch_size: 18
    generate_kwargs:
      do_sample: true
      max_new_tokens: 512
      min_new_tokens: 16
      temperature: 0.7
      repetition_penalty: 1.1
      top_p: 0.8
      top_k: 50
scaling_config:
  num_workers: 1
  num_gpus_per_worker: {num_gpus_per_worker}
  num_cpus_per_worker: 1
  placement_strategy: "STRICT_PACK"
""" 
    curr = os.path.expanduser("~")
    deploy_dir = os.path.join(curr,"byzer_model_deploy")
    deploy_file = os.path.join(curr,"byzer_model_deploy",model_id)
    if not os.path.exists(deploy_dir):
        os.makedirs(deploy_dir) 

    if os.path.exists(deploy_file):
        os.remove(deploy_file)

    with open(deploy_file, "w") as f:
        f.write(template)

    return deploy_file    
   
          

def build_model_serving(model_dir,num_gpus_per_worker:int=1):
    """Run the LLM Server on the local Ray Cluster

    Args:
        *models: A list of LLMApp objects or paths to yaml files defining LLMApps

    Example:
       run("models/")           # run all models in the models directory
       run("models/model.yaml") # run one model in the model directory
       run({...LLMApp})         # run a single LLMApp
       run("models/model1.yaml", "models/model2.yaml", {...LLMApp}) # mix and match
    """
    deployments, model_configs = llm_server([_build_yaml(model_dir,num_gpus_per_worker=num_gpus_per_worker)])
    ray._private.usage.usage_lib.record_library_usage("aviary")
    model_id, deployment = deployments.items()[0]
    model_id = model_id.replace("/", "--").replace(".", "_")
    model_infer =  serve.run(
            deployment,
            name=model_id,
            route_prefix=f"/{model_id}",
            host="127.0.0.1",
            port=int(_get_free_port()),
            _blocking=False,
        )
    return model_infer
        