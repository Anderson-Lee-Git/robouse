"""The GPU liquid backend of household liquid contract 1.2.0: `solver.WarpFluid`, the CPU `solver.Fluid`'s
interface and validity semantics with the DFSPH step on a CUDA device through NVIDIA Warp (`kernels`, `sampling`: the
adopted RoboCasa liquid 0.5.0 kernels, byte for byte). Importing this package needs neither Warp nor a GPU; building
a fluid needs both and refuses otherwise.
"""
