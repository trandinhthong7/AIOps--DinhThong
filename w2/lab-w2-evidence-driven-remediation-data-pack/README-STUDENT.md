# Evidence-Driven Remediation Engine

Run from this directory with Python 3. No external service is required.

```bash
rm -f audit.jsonl
for i in 01 02 03 04 05 06 07 08; do
  python3 engine.py decide --incident eval/E$i.json \
                           --history incidents_history.json \
                           --actions actions.yaml
done
python3 grade.py --audit audit.jsonl --expected eval/expected.json
```

The engine writes one JSON decision per incident to stdout and appends the same decision to `audit.jsonl`. The pipeline is split into `features.py` for log/trace/metric extraction, `retrieval.py` for hybrid similarity and outcome-weighted action voting, and `decision.py` for cost/blast-radius/OOD gates. Current local grade is `8/8` correct with `0/8` forbidden actions.
