# AI / Coding-Assistant Usage

## Tools used

ChatGPT was used as a development and documentation assistant to:
- Interpret the assignment requirements and review the architecture, WebSocket protocol, caption revision rules, recovery semantics, and backpressure design
- Explain Ubuntu test errors
- Analyse three-run performance results, including P50/P95/P99 caption age, freshness, final-caption completeness, update coverage, and slow-client isolation
- Review and refine the technical report, architecture diagram, and reproducibility instructions

## One useful suggestion

ChatGPT recommended treating final-caption completeness and update coverage as separate measures and investigating any completeness value above 100% rather than accepting the aggregate summary at face value. An initial set of experiment outputs reported impossible completeness values, including 200% for T1 and approximately 147% for T3. We consequently isolated the public tests in a fresh results directory, examined the counts, and repeated the workloads three times per scenario.

In the resulting clean T1–T5 summary, the reported three-run median final-caption completeness was 100% across all nine workload scenarios, with zero reported duplicate and stale messages. For example, T2 achieved a P95 caption age of 26.7ms, and T3 achieved 26.9ms overall P95 while retaining 94.39% live-revision coverage. Under combined delay and loss, P95 was 587.6 ms, fresh-final delivery was 93.33%, and live-revision coverage was 56.95%, despite 100% median final completeness.

This distinction helped us explain why receiving all final captions does not necessarily mean that every intermediate revision arrives or that captions remain fresh under impairment. The clean results establish the reported medians; they do not, by themselves, identify the cause of the earlier invalid measurements or prove hidden-test performance

## One suggestion that was wrong, inefficient, or required modification

An earlier AI-assisted testing and documentation suggestion placed the command python solution_server.py --port 8765 alongside the automated public experiment commands without clearly distinguishing the workflows. This was misleading because run_demo.py starts and stops its own server instance. Manually leaving a server bound to port 8765 can cause an OSError: [Errno 98] address already in use and prevent an automated run from starting correctly.

We corrected the procedure by separating manual application demonstration (start the server, browser client, and deterministic source in separate terminals) from automated benchmarks (do not run an additional server; let the experiment harness manage it). We also used isolated result directories when validating anomalous metrics rather than treating an AI-proposed explanation, such as residual history, as a confirmed root cause. This experience demonstrated the need to verify AI-generated operational instructions against the actual source code and test harness.

A separate reporting correction was necessary when new Ubuntu runs superseded previously quoted measurements. We updated the report using the latest three-run summary, rather than retaining the older AI-drafted figures.

## Verification and Responsibility
The latest clean T1–T5 figures cited above are medians of three runs per scenario, as reported by experiments/summarise.py. They should not be confused with earlier FIFO/coalesce/adaptive comparisons, which are separate historical measurements and may have been collected against a different code revision.

AI did not perform the Ubuntu measurements or independently certify correctness; the team executed the tests, reviewed the outputs, and remains responsible for all submitted code, documentation, results, and claims. Every member is expected to understand and defend the relevant implementation and engineering decisions during the viva.

## Responsibility statement

We understand that the team remains responsible for the submitted code, experimental results, and claims, and that every member may be asked to explain or modify relevant code during the viva.
