from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""

    # Database
    # 우선순위: DATABASE_URL 환경변수 → SUPABASE_DB_HOST + SUPABASE_DB_PASSWORD 조합
    DATABASE_URL: str = ""
    # Supabase connection pooler 개별 필드 (DATABASE_URL이 없을 때 사용)
    SUPABASE_DB_HOST: Optional[str] = None      # e.g. aws-0-ap-northeast-2.pooler.supabase.com
    SUPABASE_DB_PASSWORD: Optional[str] = None  # Supabase DB 비밀번호
    SUPABASE_DB_PORT: int = 5432
    SUPABASE_DB_NAME: str = "postgres"
    SUPABASE_DB_USER: str = "postgres"          # transaction pooler: postgres.[project-ref]

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # OpenAI (gpt-4o-mini — orchestrator tool_use)
    OPENAI_API_KEY: str = ""

    # Groq (레거시, 필요 시 유지)
    GROQ_API_KEY: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    # 프로덕션 프론트엔드 URL (Vercel 배포 후 설정)
    FRONTEND_URL: Optional[str] = None

    # App
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "AgriFlow API"
    PORT: int = 8000

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_database_url(self) -> str:
        """
        실제 사용할 DATABASE_URL을 반환한다.
        1. DATABASE_URL 환경변수가 설정되어 있으면 그대로 사용
        2. 없으면 SUPABASE_DB_HOST + SUPABASE_DB_PASSWORD로 조합
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        if self.SUPABASE_DB_HOST and self.SUPABASE_DB_PASSWORD:
            return (
                f"postgresql+asyncpg://{self.SUPABASE_DB_USER}:{self.SUPABASE_DB_PASSWORD}"
                f"@{self.SUPABASE_DB_HOST}:{self.SUPABASE_DB_PORT}/{self.SUPABASE_DB_NAME}"
            )
        # 둘 다 없으면 빈 문자열 반환 (startup 시 에러로 잡힘)
        return self.DATABASE_URL

    def get_cors_origins(self) -> list[str]:
        """
        CORS_ORIGINS에 FRONTEND_URL을 동적으로 추가하여 반환한다.
        """
        origins = list(self.CORS_ORIGINS)
        if self.FRONTEND_URL and self.FRONTEND_URL not in origins:
            origins.append(self.FRONTEND_URL)
        return origins


settings = Settings()
