"""
ArtCheck - Streamlit Version
Instant art file preview generator
"""

import streamlit as st
import subprocess
import os
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import shutil
import tempfile

st.set_page_config(
    page_title="ArtCheck - Preview Generator",
    page_icon="🎨",
    layout="wide"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .tagline {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: bold;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background: #e8f5e9;
        border-left: 4px solid #2e7d32;
        margin: 1rem 0;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background: #e3f2fd;
        border-left: 4px solid #1976d2;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)


class PreviewGenerator:
    """Handles conversion of vector files to PNG previews"""
    
    SUPPORTED_FORMATS = ['.ai', '.eps', '.pdf', '.svg']
    DEFAULT_DPI = 300
    PREVIEW_MAX_WIDTH = 1200
    PREVIEW_MAX_HEIGHT = 1200
    
    def __init__(self):
        self.has_inkscape = shutil.which('inkscape') is not None
        self.has_imagemagick = shutil.which('convert') is not None
    
    def is_supported(self, filename):
        """Check if file format is supported"""
        return Path(filename).suffix.lower() in self.SUPPORTED_FORMATS
    
    def _convert_with_inkscape(self, input_file, output_file, dpi):
        """Convert using Inkscape"""
        try:
            cmd = [
                'inkscape',
                str(input_file),
                '--export-type=png',
                f'--export-dpi={dpi}',
                f'--export-filename={output_file}'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0 and os.path.exists(output_file)
        except Exception as e:
            st.error(f"Inkscape error: {e}")
            return False
    
    def _convert_with_imagemagick(self, input_file, output_file, dpi):
        """Convert using ImageMagick"""
        try:
            input_path = Path(input_file)
            ext = input_path.suffix.lower()
            
            if ext == '.svg':
                cmd = ['convert', '-background', 'none', '-density', str(dpi), 
                       str(input_file), str(output_file)]
            else:
                cmd = ['convert', '-density', str(dpi), '-background', 'none',
                       f'{input_file}[0]', '-flatten', str(output_file)]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0 and os.path.exists(output_file)
        except Exception as e:
            st.error(f"ImageMagick error: {e}")
            return False
    
    def detect_brightness(self, img):
        """Detect average brightness"""
        gray = img.convert('L')
        pixels = list(gray.getdata())
        return sum(pixels) / len(pixels)
    
    def add_background(self, img, bg_type='auto'):
        """Add background to image"""
        if bg_type == 'auto':
            brightness = self.detect_brightness(img)
            bg_type = 'dark' if brightness > 200 else 'light'
        
        if bg_type == 'transparent':
            return img.convert('RGBA')
        
        bg_colors = {
            'dark': (45, 45, 48),
            'light': (240, 240, 240),
        }
        
        bg_color = bg_colors.get(bg_type, bg_colors['light'])
        
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        background = Image.new('RGB', img.size, bg_color)
        background.paste(img, (0, 0), img)
        
        return background
    
    def add_watermark(self, img):
        """Add watermark"""
        watermarked = img.copy()
        draw = ImageDraw.Draw(watermarked)
        
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except:
            font = ImageFont.load_default()
        
        text = "ArtCheck Preview"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = img.width - text_width - 10
        y = img.height - text_height - 10
        
        padding = 5
        draw.rectangle(
            [(x - padding, y - padding), 
             (x + text_width + padding, y + text_height + padding)],
            fill=(255, 255, 255, 200)
        )
        draw.text((x, y), text, fill=(100, 100, 100), font=font)
        
        return watermarked
    
    def generate_preview(self, input_file, bg_type='auto', dpi=300):
        """Generate preview from input file"""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_output = temp_file.name
        
        # Try conversion
        success = False
        if self.has_inkscape:
            success = self._convert_with_inkscape(input_file, temp_output, dpi)
        
        if not success and self.has_imagemagick:
            success = self._convert_with_imagemagick(input_file, temp_output, dpi)
        
        if not success:
            return None
        
        # Process image
        try:
            img = Image.open(temp_output)
            
            # Resize if needed
            width_scale = self.PREVIEW_MAX_WIDTH / img.width
            height_scale = self.PREVIEW_MAX_HEIGHT / img.height
            scale = min(width_scale, height_scale, 1.0)
            
            if scale < 1.0:
                new_width = int(img.width * scale)
                new_height = int(img.height * scale)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            brightness = self.detect_brightness(img)
            img = self.add_background(img, bg_type)
            img = self.add_watermark(img)
            
            # Save final
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as final_file:
                final_output = final_file.name
            
            img.save(final_output, 'PNG', optimize=True)
            
            # Cleanup temp
            if os.path.exists(temp_output):
                os.unlink(temp_output)
            
            return {
                'image': img,
                'path': final_output,
                'width': img.width,
                'height': img.height,
                'brightness': round(brightness, 1),
                'size_kb': round(os.path.getsize(final_output) / 1024, 2)
            }
            
        except Exception as e:
            st.error(f"Processing error: {e}")
            return None


# Initialize generator
@st.cache_resource
def get_generator():
    return PreviewGenerator()

generator = get_generator()

# Header
st.markdown('<div class="main-header">🎨 ArtCheck - IT WORKS!</div>', unsafe_allow_html=True)
st.markdown('<div class="tagline">Instant Vector File Preview Generator</div>', unsafe_allow_html=True)

# Check for tools
col1, col2 = st.columns(2)
with col1:
    if generator.has_inkscape:
        st.success("✅ Inkscape detected - Production quality enabled!")
    else:
        st.warning("⚠️ Inkscape not detected - Install for best quality")

with col2:
    if generator.has_imagemagick:
        st.success("✅ ImageMagick detected")
    else:
        st.info("ℹ️ ImageMagick not detected (optional)")

st.markdown("---")

# File upload
uploaded_file = st.file_uploader(
    "Upload a file",
    type=['ai', 'eps', 'pdf', 'svg'],
    help="Supports AI, EPS, PDF, and SVG files up to 200MB"
)

if uploaded_file:
    # Background options
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        bg_auto = st.button("🔄 Auto", use_container_width=True, type="primary")
    with col2:
        bg_light = st.button("☀️ Light", use_container_width=True)
    with col3:
        bg_dark = st.button("🌙 Dark", use_container_width=True)
    with col4:
        bg_transparent = st.button("⬜ Transparent", use_container_width=True)
    
    # Determine background type
    bg_type = 'auto'
    if bg_light:
        bg_type = 'light'
    elif bg_dark:
        bg_type = 'dark'
    elif bg_transparent:
        bg_type = 'transparent'
    
    # Generate preview button
    if st.button("🚀 Generate Preview", use_container_width=True, type="primary"):
        with st.spinner("Generating preview..."):
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                tmp_file.write(uploaded_file.getbuffer())
                tmp_path = tmp_file.name
            
            # Generate preview
            result = generator.generate_preview(tmp_path, bg_type)
            
            # Cleanup temp upload
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            
            if result:
                st.markdown('<div class="success-box">✅ Preview generated successfully!</div>', 
                          unsafe_allow_html=True)
                
                # Display preview
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.image(result['image'], caption="Your Preview", use_container_width=True)
                
                with col2:
                    st.markdown("### Preview Info")
                    st.metric("Dimensions", f"{result['width']} × {result['height']}")
                    st.metric("File Size", f"{result['size_kb']} KB")
                    st.metric("Background", bg_type.title())
                    st.metric("Brightness", f"{result['brightness']}")
                    
                    # Download button
                    with open(result['path'], 'rb') as f:
                        st.download_button(
                            label="⬇️ Download Preview",
                            data=f,
                            file_name=f"{Path(uploaded_file.name).stem}_preview.png",
                            mime="image/png",
                            use_container_width=True
                        )
                    
                    # Cleanup
                    if os.path.exists(result['path']):
                        os.unlink(result['path'])
            else:
                st.error("❌ Failed to generate preview. Please try a different file.")

# Features
st.markdown("---")
st.markdown("### ✨ Features")

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**⚡ 3-Second Generation**")
    st.write("Lightning-fast preview creation")

with col2:
    st.markdown("**🎨 Smart Detection**")
    st.write("Auto-detects best background")

with col3:
    st.markdown("**💾 Instant Download**")
    st.write("Get your PNG immediately")

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Built with ❤️ for promotional products professionals</p>
    <p>Save your art department 15+ hours per week</p>
</div>
""", unsafe_allow_html=True)
