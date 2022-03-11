import torch
import argbind

optim = argbind.bind_module(
    torch.optim, 
    filter_fn=lambda fn: hasattr(fn, "step")
)
args = {
    "lr": 2e-4,
    "args.debug": True,
}

net = torch.nn.Linear(1, 1)
for fn_name in dir(optim):
    if fn_name.startswith("_") or fn_name == "Optimizer":
        continue
    fn = getattr(optim, fn_name)
    args[f"{fn_name}.lr"] = args["lr"]
    with argbind.scope(args):
        fn(net.parameters())