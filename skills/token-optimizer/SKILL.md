<skill>
  <name>token-optimizer</name>
  <description>Extreme token optimizer that achieves up to 98% reduction in context size. Extracts only the absolute structural bare-metal logic (function signatures, class names, top-level API definitions, and core nouns). Use when dealing with massive codebases or immense documents where only the highest-level architecture is needed to avoid context overflow.</description>
  <usage>
    Use `python D:\openclaw\skills\token-optimizer\optimizer.py [file_path]` to compress a file.
    Or pipe text into it: `cat file.txt | python optimizer.py`
  </usage>
  <examples>
    <example>
      User: "Give me an overview of this massive 10,000 line file, I just need the structure."
      Assistant: python D:\openclaw\skills\token-optimizer\optimizer.py D:\massive_file.py
    </example>
  </examples>
  <implementation>
    <command>python D:\openclaw\skills\token-optimizer\optimizer.py</command>
    <arguments>
      <arg name="file_path" type="string" required="true" description="Path to the file to optimize" />
    </arguments>
  </implementation>
</skill>