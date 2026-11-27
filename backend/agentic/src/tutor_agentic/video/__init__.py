"""Video summary generation for the agentic tutor layer.

Pipeline:
  EducationalContent
    → script_from_content()   (script.py)  → list[Slide]
    → render_slides_to_mp4()  (renderer.py) → MP4 file
    → AssetRegistry.register()              → asset_id
    → VideoBlock                            → UISpec

Both Pillow and moviepy must be installed. If they are missing the
generate_video graph node is a no-op (video block is simply not added).
"""

from .renderer import render_slides_to_mp4
from .script import Slide, script_from_content

__all__ = ["Slide", "script_from_content", "render_slides_to_mp4"]
