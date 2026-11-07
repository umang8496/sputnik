"""Exercise 4: force failures and watch the SDK's retry behavior.
Run from triage/:
    python ../week-02/exercises/e4_failures.py badkey     # 401: must fail fast, no retries
    python ../week-02/exercises/e4_failures.py 529        # needs scripts/fake_529.py running
Cost: $0 (no request reaches a real model)."""
import os, sys, time

mode = sys.argv[1] if len(sys.argv) > 1 else "badkey"
# Set env BEFORE importing triage.llm: the client reads it when it is constructed.
# (load_dotenv() does not override variables that are already set.)
if mode == "badkey":
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-api03-bad"
elif mode == "529":
    os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:8529"
else:
    sys.exit("mode must be badkey or 529")

sys.path.insert(0, "src")
import anthropic
from triage.llm import call, client, LLMError

print(f"client config: timeout={client.timeout}  max_retries={client.max_retries}")
t0 = time.perf_counter()
try:
    call("ping", tag=f"w02.e4.{mode}", max_tokens=16)
    code = 0
except anthropic.AuthenticationError as e:                      # 401: config problem, never retried
    print(f"AuthenticationError status={e.status_code}")
    code = 2
except (anthropic.RateLimitError,                               # 429 after retries
        anthropic.InternalServerError,                          # 5xx / 529 after retries
        anthropic.APIConnectionError) as e:                     # network / timeout after retries
    print(f"{type(e).__name__} status={getattr(e, 'status_code', None)}")
    code = 3
except anthropic.APIStatusError as e:                           # any other HTTP error
    print(f"{type(e).__name__} status={e.status_code} type={getattr(e, 'type', None)}")
    code = 5
except LLMError as e:
    print(f"LLMError {e}")
    code = 4
print(f"elapsed {time.perf_counter() - t0:.1f}s -> exit code {code}")
sys.exit(code)
