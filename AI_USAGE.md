# AI / Coding-Assistant Usage

## Tools used

List the generative-AI/coding tools used by the team and what each was used for.
ChatGPT was used as a development and documentation assistant to:
- Interpret the assignment requirements and review the architecture, WebSocket protocol, caption revision rules, recovery semantics, and backpressure design
- Explain Ubuntu test errors
- Analyse three-run performance results, including P50/P95/P99 caption age, freshness, final-caption completeness, update coverage, and slow-client isolation
- Review and refine the technical report, architecture diagram, and reproducibility instructions

## One useful suggestion

ChatGPT recommended evaluating semantic backpressure using both latency and correctness, and separating overall latency from normal-client and slow-client latency, instead of reporting only an aggregate P95. This helped us interpret and present the controlled comparison of FIFO, provisional-revision coalescing, and adaptive delivery under the same 100-client workload with 10 slow readers.

The latest comparison was verified using three independent Ubuntu runs per policy and the public analysis scripts. Adaptive delivery achieved an overall P95 caption age of 27.0 ms, compared with 2,254.2 ms for coalescing, while increasing final-caption completeness from 95.13% to 100.00%. The comparison also revealed a trade-off: normal-client P95 increased from 18.2 ms under coalescing to 24.0 ms under adaptive delivery. These findings demonstrate why latency, completeness and slow-client isolation must be evaluated together.

## One suggestion that was wrong, inefficient, or required modification

An early AI-assisted reproducibility draft placed the manual server-start command, python solution_server.py --port 8765, alongside commands for the automated public experiments without clearly distinguishing the two workflows. This was misleading as run_demo.py and the experiment scripts start their own server. Leaving a manually launched instance on port 8765 can prevent the test server from starting. During testing, a port conflict produced OSError: [Errno 98] address already in use, followed by a caption-source connection error.

We corrected the documentation to separate (1) manual startup for the browser demonstration from (2) automated testing, which must execute without a separate server instance. The corrected procedure also uses ss -ltnp to check whether the port is occupied before rerunning a test. This illustrates why AI-generated operational instructions must be checked against the test harness's actual process lifecycle.

A separate reporting correction was necessary when new Ubuntu runs superseded previously quoted measurements. We updated the report using the latest three-run summary, rather than retaining the older AI-drafted figures.

## Responsibility statement

We understand that the team remains responsible for the submitted code, experimental results, and claims, and that every member may be asked to explain or modify relevant code during the viva.
