"""Agent definitions, registry, prompts, and execution adapters.

Consumers import concrete objects from their defining modules. Avoiding eager
provider imports keeps the provider/tool/harness dependency direction acyclic.
"""
