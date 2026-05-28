import os
from dotenv import load_dotenv
load_dotenv()

from phoenix.client import Client

client = Client(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)
spans = client.spans.get_spans(
    project_identifier=os.getenv("PHOENIX_PROJECT_NAME", "gemini-hackathon"),
    limit=50,
)
print("Total spans in project:", len(spans))
for s in spans[:20]:
    print(f"  {s.get('name'):40s} kind={s.get('span_kind')} status={(s.get('status') or {}).get('code')}")
