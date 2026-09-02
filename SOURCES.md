# Sources

Two, and they are the same kind of thing.

**S1 --- Dally, W. J. "Performance Analysis of k-Ary n-Cube Interconnection
Networks." *IEEE Transactions on Computers* 39(6), 1990, pp. 775--785.**
Used for the closed forms this repository pins its calibrated points to:
diameter `n*floor(k/2)` for a torus and `n*(k-1)` for a mesh; bisection
`2k^(n-1)` and `k^(n-1)` respectively.

**S2 --- Duato, J., Yalamanchili, S., and Ni, L. *Interconnection Networks: An
Engineering Approach.* Morgan Kaufmann, 2003, ch. 1.** The same closed forms,
independently stated, which is why both are cited on both calibrated points.

## What these sources are not

They are textbook results about an idealised topology. Agreeing with them
demonstrates that `torus.py` implements a k-ary n-cube correctly. It does not
demonstrate that any pod is a k-ary n-cube, that the extents used in the
examples resemble any machine, or that a real slice behaves the way this model
says.

**There is no measurement in this repository.** No pod, no scheduler, no
failure, no tenant. Every other number here --- fragmentation, cordon cost,
isolation cost, the autonomy boundary --- is a model output derived from stated
rules, and is offered as something to disagree with rather than something to
cite. The validation registry prints that as declined items 1 and 2, above the
results, on every run.
