# Sources

Three. The first two are the same kind of thing; the third is the opposite kind.

**S1 --- Dally, W. J. "Performance Analysis of k-Ary n-Cube Interconnection
Networks." *IEEE Transactions on Computers* 39(6), 1990, pp. 775--785.**
Used for the closed forms this repository pins its calibrated points to:
diameter `n*floor(k/2)` for a torus and `n*(k-1)` for a mesh; bisection
`2k^(n-1)` and `k^(n-1)` respectively.

**S2 --- Duato, J., Yalamanchili, S., and Ni, L. *Interconnection Networks: An
Engineering Approach.* Morgan Kaufmann, 2003, ch. 1.** The same closed forms,
independently stated, which is why both are cited on both calibrated points.

**S3 --- Ostrouchov, G., Maxwell, D., Ashraf, R. A., Engelmann, C., Shankar,
M., and Rogers, J. H. "GPU Lifetimes on Titan Supercomputer: Survival Analysis
and Reliability." *SC '20*, ACM, 2020. Data: github.com/olcf/TitanGPULife,
DOI 10.13139/ORNLNCCS/1657202.** The per-GPU summary of 30,207 GPUs over
100,000 collective GPU-years, fetched and SHA-pinned by `make data`, and the
paper whose findings the three Titan calibrated points reproduce from it: the
headline exposure, the cage ordering the authors attribute to cooling-air
transport, and the no-bathtub hazard curve. Upstream asks users of the data to
cite the paper; this repository does, here and in the registry.

## What these sources are not

S1 and S2 are textbook results about an idealised topology. Agreeing with them
demonstrates that `torus.py` implements a k-ary n-cube correctly. It does not
demonstrate that any pod is a k-ary n-cube, that the extents used in the
examples resemble any machine, or that a real slice behaves the way this model
says.

**There is exactly one measurement in this repository, and it is S3.** It
measures failures, not packing: no pod geometry, no scheduler, no tenant here
has met a machine. Every geometry number --- fragmentation, cordon cost,
isolation cost, the autonomy boundary --- is a model output derived from stated
rules, and is offered as something to disagree with rather than something to
cite. And S3's rates are Titan's own (ASSUMPTIONS A12): what the hazard module
takes from them is the shape, never a number for another machine. The
validation registry prints all of this as declined items 1, 2 and 15, above
the results, on every run.
