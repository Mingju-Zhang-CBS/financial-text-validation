"""Trace one actual public event through measurement, publication and target clocks."""
from pathlib import Path
import json
import numpy as np
from financial_text_validation import core

root=Path(core.__file__).parent
protocol=json.loads((root/'protocol.json').read_text(encoding='utf-8'))
statements,quotes,_=core.load_data(root/'data')
panel,_=core.build_panel(statements,quotes,protocol)
event=panel[panel.publication_date.dt.year>=2020].iloc[0]
print('Real public-data event:',event.event_id)
for field in ['publication_date','available_at','decision_at','feature_observation_date','feature_available_at','entry_date','label_end','label_available_at']:
    print(field+':',event[field])
print('USD per EUR:',event.entry_rate,'->',event.end_rate)
print('Log return:',np.log(event.end_rate/event.entry_rate),'up label:',event.target)
assert event.feature_available_at<=event.decision_at
assert event.available_at<event.decision_at
assert event.label_end>event.entry_date
