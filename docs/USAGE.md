# Current experiment design readable for human (Julian)

## Start the vm

Simply use 

```
bash scripts/laptop/gpu_up.sh
```

To check if it's serving and that `olmo` has loaded

```
curl localhost:8000/v1/models
```

## Run inspect and inspect inspect
(all with active venv)

running
```
inspect eval tasks/instrumental_eval.py --model openai-api/vllm/olmo --epochs 5 --max-connections 32 -M client_timeout=3600
```

inspecting (best in extra terminal)
```
inspect view
```


