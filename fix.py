import re

with open('config.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacement = """    groq_api_key: str = Field(default="placeholder-groq-key", env="GROQ_API_KEY")
    groq_api_keys: str = Field(default="", env="GROQ_API_KEYS")

    @property
    def all_groq_keys(self) -> list[str]:
        keys = []
        if self.groq_api_keys:
            keys.extend([k.strip() for k in self.groq_api_keys.split(",") if k.strip()])
        if self.groq_api_key and self.groq_api_key not in keys and self.groq_api_key != "placeholder-groq-key":
            keys.append(self.groq_api_key)
        return keys"""

content = content.replace('    groq_api_key: str = Field(default="placeholder-groq-key", env="GROQ_API_KEY")', replacement)

with open('config.py', 'w', encoding='utf-8') as f:
    f.write(content)
