"""
ArtCheck - Minimal Version for Testing
Just preview generation, no color analysis
"""

import streamlit as st
import os
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import tempfile

st.set_page_config(
    page_title="ArtCheck - Preview Generator",
    page_icon="🎨",
    layout="wide"
)

st.title("🎨 ArtCheck - IT WORKS!")
st.subheader("Vector & Embroidery File Preview Generator")

class PreviewGenerator:
    """Simple preview generator using CairoSVG"""
    
    def __init__(self):
        try:
            import cairosvg
            self.cairosvg = cairosvg
            self.has_cairosvg = True
        except ImportError:
            self.cairosvg = None
            self.has_cairosvg = False
    
    def generate_preview(self, uploaded_file):
        """Generate PNG preview from SVG/vector file"""
        if not self.has_cairosvg:
            return None, "CairoSVG not available"
        
        try:
            # Get file extension
            ext = Path(uploaded_file.name).suffix.lower()
            
            # Read file content
            file_content = uploaded_file.getvalue()
            
            # Create output file
            output_path = tempfile.mktemp(suffix='.png')
            
            # Convert based on format
            if ext == '.svg':
                self.cairosvg.svg2png(
                    bytestring=file_content,
                    write_to=output_path,
                    output_width=1200
                )
            elif ext in ['.eps', '.ai', '.pdf']:
                # For now, only handle SVG
                return None, f"{ext} conversion not yet implemented - try SVG first"
            else:
                return None, f"Unsupported format: {ext}"
            
            # Check if file was created
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path, "Success"
            else:
                return None, "Conversion produced empty file"
                
        except Exception as e:
            return None, f"Error: {str(e)}"


def add_watermark(image_path, output_path, watermark_text="PREVIEW"):
    """Add simple watermark to image"""
    try:
        img = Image.open(image_path).convert('RGBA')
        width, height = img.size
        
        # Create watermark layer
        watermark = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        
        # Use default font for simplicity
        font = ImageFont.load_default()
        
        # Calculate text position (center)
        text = watermark_text
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        position = ((width - text_width) // 2, (height - text_height) // 2)
        
        # Draw watermark
        draw.text(position, text, font=font, fill=(255, 255, 255, 200))
        
        # Composite and save
        result = Image.alpha_composite(img, watermark)
        result.convert('RGB').save(output_path, 'PNG')
        
        return True
    except Exception as e:
        st.error(f"Watermark error: {str(e)}")
        return False


# File Upload
st.markdown("## 📁 Upload Your File")
st.info("**Supported:** Vector files (.ai, .eps, .pdf, .svg) | Embroidery files (.dst, .pes, .exp, .jef, .vp3, .xxx, .u01)")

uploaded_file = st.file_uploader(
    "👉 Drag and drop your file here or click to browse",
    type=['svg', 'ai', 'eps', 'pdf', 'dst', 'pes', 'exp', 'jef', 'vp3', 'xxx', 'u01'],
    help="Limit 200MB per file • AI, EPS, PDF, SVG, CDR, XCF, INDD, DST, PES, EXP, JEF, VP3, XXX, U01"
)

if uploaded_file:
    st.success(f"✓ Uploaded: **{uploaded_file.name}** ({uploaded_file.size / 1024 / 1024:.2f} MB)")
    
    # Background mode (visual only for now)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        bg_auto = st.button("☀️ Auto", use_container_width=True)
    with col2:
        bg_light = st.button("☀️ Light", use_container_width=True)
    with col3:
        bg_dark = st.button("🌙 Dark", use_container_width=True)
    with col4:
        bg_transparent = st.button("▪️ Transparent", use_container_width=True)
    
    # Generate Preview
    if st.button("🚀 Generate Preview", type="primary", use_container_width=True):
        with st.spinner("Generating preview..."):
            generator = PreviewGenerator()
            
            preview_path, message = generator.generate_preview(uploaded_file)
            
            if preview_path:
                # Success!
                st.success("✅ Preview generated successfully!")
                
                # Add watermark
                watermarked_path = tempfile.mktemp(suffix='.png')
                if add_watermark(preview_path, watermarked_path, "PREVIEW"):
                    st.image(watermarked_path, use_container_width=True)
                    
                    # Show file info
                    img = Image.open(preview_path)
                    st.info(f"**Size:** {img.width} × {img.height} pixels")
                    
                    # Cleanup
                    os.unlink(watermarked_path)
                    os.unlink(preview_path)
                else:
                    # Show without watermark if watermark failed
                    st.image(preview_path, use_container_width=True)
                    os.unlink(preview_path)
            else:
                # Failed
                st.error(f"❌ Failed to generate preview. Please try a different file.")
                st.error(f"Details: {message}")

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Built with ❤️ for promotional products professionals</p>
    <p>Save your art department 15+ hours per week</p>
</div>
""", unsafe_allow_html=True)
