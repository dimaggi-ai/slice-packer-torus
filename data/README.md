# Data

`titan_gc_summary_loc.csv` — one record per GPU for the 30,207 GPUs of the
Cray XK7 Titan, from the public release accompanying:

> George Ostrouchov, Don Maxwell, Rizwan A. Ashraf, Christian Engelmann,
> Mallikarjun Shankar, and James H. Rogers. 2020. *GPU Lifetimes on Titan
> Supercomputer: Survival Analysis and Reliability.* SC '20.
> Data: https://github.com/olcf/TitanGPULife (DOI 10.13139/ORNLNCCS/1657202)

The file is **fetched, not vendored** (`make data` or `sh data/fetch_titan.sh`),
because upstream publishes it with a citation request and no explicit license
grant. The fetch pins a SHA-256, so what the registry measures is exactly the
file this repository's numbers were written against. If using the data, cite
the paper above — their request, passed on.
