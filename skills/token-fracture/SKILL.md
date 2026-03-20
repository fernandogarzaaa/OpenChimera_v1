<skill>
  <name>token-fracture</name>
  <description>Compress text context using CHIMERA's Token Fracture algorithm (68%+ reduction). Use when user asks to compress text, reduce tokens, or fit more context into a prompt.</description>
  <usage>
    Use `token_fracture(text, ratio)` to compress text.
    - text: The text to compress.
    - ratio: Compression ratio (0.1 to 0.9, default 0.5). Lower = more compression.
  </usage>
  <examples>
    <example>
      User: "Compress this long article for me."
      Assistant: token_fracture(text=article_text, ratio=0.3)
    </example>
  </examples>
  <implementation>
    <command>python skills/token-fracture/fracture_client.py</command>
    <arguments>
      <arg name="text" type="string" required="true" description="Text to compress" />
      <arg name="ratio" type="number" required="false" default="0.5" description="Compression ratio (0.1-0.9)" />
    </arguments>
  </implementation>
</skill>