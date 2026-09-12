"""Phase 0 exit criterion: one Bedrock call succeeds. Run: uv run scripts/check_bedrock.py"""
from strands import Agent
from strands.models import BedrockModel

from flakeguard.config import load

cfg = load().bedrock
agent = Agent(model=BedrockModel(model_id=cfg.model_id, region_name=cfg.region), callback_handler=None)
reply = agent("Reply with exactly the word OK.")
print(f"model={cfg.model_id} region={cfg.region} reply={str(reply).strip()!r}")
assert "OK" in str(reply)
