"""Application settings (adapted from the reference project's config.py).

Provider-agnostic: the reference hard-coded GWDG; here the LLM layer is configured
generically so we can point at Anthropic (default), OpenAI, or a local endpoint.
Credential guards fail fast on the *live* paths only — unit tests instantiate
``Settings()`` without keys and run fully offline.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingCredentialsError(RuntimeError):
    """Raised when live credentials are required but not configured."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM. Default: DeepSeek via its OpenAI-compatible API.
    llm_provider: str = Field(default="deepseek")
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.deepseek.com")  # OpenAI-compatible
    llm_model: str = Field(default="deepseek-chat")  # or "deepseek-reasoner"

    # Embeddings (DeepSeek has none) — any OpenAI-protocol endpoint: OpenAI, Jina,
    # Voyage, or a local server (ollama / text-embeddings-inference) via base_url.
    embedding_provider: str = Field(default="openai")
    embedding_api_key: str = Field(default="")
    embedding_base_url: str = Field(default="")  # set for Jina/Voyage/local; blank = OpenAI
    embedding_model: str = Field(default="text-embedding-3-small")

    # Persistence (Supabase Postgres + pgvector), same as the reference.
    supabase_url: str = Field(default="")
    supabase_key: str = Field(default="")

    # Swiss business register (Zefix) requires a registered API account (Basic auth).
    zefix_username: str = Field(default="")
    zefix_password: str = Field(default="")

    # Brave Search API — used to resolve company name -> website for brute-force crawl.
    brave_api_key: str = Field(default="")

    # ReliefWeb (Track-B intl-org jobs). Since 2025-11-01 the API requires a
    # PRE-APPROVED appname (register at https://reliefweb.int/help/api). Without one,
    # the ReliefWeb source is skipped silently. Set this once approved to enable it.
    reliefweb_appname: str = Field(default="")

    # JSearch (RapidAPI) — aggregates Google for Jobs, so it reaches established
    # employers that hire via their own career pages (not just LinkedIn) across all
    # countries incl. Czechia. Free key at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
    rapidapi_key: str = Field(default="")

    # Adzuna — European job aggregator with structured search, salary data, and
    # location scoping.  Covers CH, DE, AT, FR, NL, BE, IT, PL, CZ.  Free API
    # key at https://developer.adzuna.com
    adzuna_app_id: str = Field(default="")
    adzuna_app_key: str = Field(default="")

    # Keyword extraction LLM (cheap/fast, e.g. Mistral-small) — used to extract
    # domain-specific search terms from the candidate profile.  Separate from the
    # main LLM (DeepSeek) so keyword extraction doesn't compete with CV parsing /
    # cover-letter generation for quota.  Falls back to heuristic extraction when
    # not configured.
    keyword_llm_api_key: str = Field(default="")
    keyword_llm_base_url: str = Field(default="https://api.mistral.ai/v1")
    keyword_llm_model: str = Field(default="mistral-small-latest")

    @property
    def zefix_auth_header(self) -> str | None:
        if not (self.zefix_username and self.zefix_password):
            return None
        import base64

        token = base64.b64encode(f"{self.zefix_username}:{self.zefix_password}".encode()).decode()
        return f"Basic {token}"

    log_level: str = Field(default="INFO")
    artifacts_dir: Path = Field(default=Path("./artifacts"))

    def require_llm_credentials(self) -> None:
        if not self.llm_api_key:
            raise MissingCredentialsError(
                "Missing LLM_API_KEY. Copy .env.example to .env and fill it in."
            )

    def require_db_credentials(self) -> None:
        missing = [
            name
            for name, val in (("SUPABASE_URL", self.supabase_url), ("SUPABASE_KEY", self.supabase_key))
            if not val
        ]
        if missing:
            raise MissingCredentialsError(
                f"Missing required env vars: {', '.join(missing)}. "
                "Copy .env.example to .env and fill them in."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
