"""
ArtCheck - Enhanced with Embroidery File Support
Handles vector files AND embroidery files (.dst, .pes, .exp, etc.)
CLOUD-OPTIMIZED VERSION - Uses CairoSVG, pdf2image, reportlab instead of Inkscape/ImageMagick
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

# Custom CSS
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
    .success-box {
        padding: 1.5rem;
        border-radius: 0.5rem;
        background: #d4edda;
        border: 3px solid #28a745;
        margin: 1rem 0;
        color: #155724;
        font-size: 1.1rem;
        font-weight: bold;
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


class EmbroideryConverter:
    """Handles embroidery file conversion to PNG"""
    
    EMBROIDERY_FORMATS = ['.dst', '.pes', '.exp', '.jef', '.vp3', '.xxx', '.u01']
    
    def __init__(self):
        try:
            import pyembroidery
            self.pyembroidery = pyembroidery
            self.available = True
        except ImportError:
            self.pyembroidery = None
            self.available = False
    
    def is_embroidery_file(self, filename):
        """Check if file is an embroidery format"""
        return Path(filename).suffix.lower() in self.EMBROIDERY_FORMATS
    
    def convert_to_png(self, input_file, output_file, width=1200, height=800):
        """Convert embroidery file to PNG visualization"""
        if not self.available:
            return False, "pyembroidery not installed"
        
        try:
            # Read embroidery file
            pattern = self.pyembroidery.read(str(input_file))
            
            # Create visualization
            img = Image.new('RGB', (width, height), 'white')
            draw = ImageDraw.Draw(img)
            
            # Get pattern bounds
            bounds = pattern.bounds()
            if not bounds or len(bounds) != 4:
                return False, "Could not determine pattern bounds"
            
            min_x, min_y, max_x, max_y = bounds
            
            # Calculate scaling
            pattern_width = max_x - min_x
            pattern_height = max_y - min_y
            
            if pattern_width == 0 or pattern_height == 0:
                return False, "Pattern has zero dimensions"
            
            # Add margins
            margin = 50
            scale_x = (width - 2 * margin) / pattern_width
            scale_y = (height - 2 * margin) / pattern_height
            scale = min(scale_x, scale_y)
            
            # Center the pattern
            offset_x = margin + (width - 2 * margin - pattern_width * scale) / 2
            offset_y = margin + (height - 2 * margin - pattern_height * scale) / 2
            
            # Draw stitches
            prev_x = prev_y = None
            current_color = (0, 0, 0)  # Default black
            
            for stitch in pattern.stitches:
                x, y = stitch[0], stitch[1]
                flags = stitch[2] if len(stitch) > 2 else 0
                
                # Scale and translate coordinates
                screen_x = offset_x + (x - min_x) * scale
                screen_y = offset_y + (y - min_y) * scale
                
                # Handle color changes
                if flags & self.pyembroidery.TRIM or flags & self.pyembroidery.COLOR_CHANGE:
                    prev_x = prev_y = None
                
                # Draw stitch line
                if prev_x is not None and not (flags & self.pyembroidery.JUMP):
                    draw.line(
                        [(prev_x, prev_y), (screen_x, screen_y)],
                        fill=current_color,
                        width=2
                    )
                
                prev_x, prev_y = screen_x, screen_y
            
            # Save image
            img.save(output_file, 'PNG')
            
            # Get pattern info
            stitch_count = len(pattern.stitches)
            thread_changes = sum(1 for s in pattern.stitches if len(s) > 2 and (s[2] & self.pyembroidery.COLOR_CHANGE))
            
            return True, {
                'stitch_count': stitch_count,
                'thread_changes': thread_changes,
                'width_mm': round(pattern_width / 10, 2),  # Convert to mm
                'height_mm': round(pattern_height / 10, 2)
            }
            
        except Exception as e:
            return False, f"Conversion error: {str(e)}"


class PreviewGenerator:
    """Handles conversion of vector files to PNG previews - CLOUD OPTIMIZED"""
    
    SUPPORTED_FORMATS = ['.ai', '.eps', '.pdf', '.svg', '.cdr', '.xcf']
    DEFAULT_DPI = 300
    PREVIEW_MAX_WIDTH = 1200
    PREVIEW_MAX_HEIGHT = 1200
    
    def __init__(self):
        self.embroidery = EmbroideryConverter()
        
        # Check for available conversion libraries
        try:
            import cairosvg
            self.cairosvg = cairosvg
            self.has_cairosvg = True
        except ImportError:
            self.cairosvg = None
            self.has_cairosvg = False
        
        try:
            from pdf2image import convert_from_path
            self.pdf2image_convert = convert_from_path
            self.has_pdf2image = True
        except ImportError:
            self.pdf2image_convert = None
            self.has_pdf2image = False
    
    def is_supported(self, filename):
        """Check if file format is supported"""
        ext = Path(filename).suffix.lower()
        return ext in self.SUPPORTED_FORMATS or self.embroidery.is_embroidery_file(filename)
    
    def _convert_svg_with_cairosvg(self, input_file, output_file):
        """Convert SVG to PNG using CairoSVG"""
        if not self.has_cairosvg:
            return False
        
        try:
            with open(input_file, 'rb') as f:
                svg_content = f.read()
            
            self.cairosvg.svg2png(
                bytestring=svg_content,
                write_to=output_file,
                output_width=self.PREVIEW_MAX_WIDTH
            )
            
            return os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception as e:
            st.warning(f"CairoSVG conversion failed: {str(e)}")
            return False
    
    def _convert_pdf_with_pdf2image(self, input_file, output_file):
        """Convert PDF to PNG using pdf2image (uses poppler)"""
        if not self.has_pdf2image:
            return False
        
        try:
            images = self.pdf2image_convert(
                input_file,
                dpi=200,
                first_page=1,
                last_page=1,
                fmt='png'
            )
            
            if images:
                # Resize if too large
                img = images[0]
                if img.width > self.PREVIEW_MAX_WIDTH or img.height > self.PREVIEW_MAX_HEIGHT:
                    img.thumbnail((self.PREVIEW_MAX_WIDTH, self.PREVIEW_MAX_HEIGHT), Image.Resampling.LANCZOS)
                
                img.save(output_file, 'PNG')
                return True
            return False
        except Exception as e:
            st.warning(f"PDF conversion failed: {str(e)}")
            return False
    
    def _convert_eps_ai_with_ghostscript(self, input_file, output_file):
        """Convert EPS/AI using Ghostscript directly for high-quality rendering"""
        try:
            import subprocess
            
            # Use ghostscript directly for high-quality conversion
            # -r300 = 300 DPI for crisp output
            # -dEPSCrop = Crop to artwork bounding box, not full page
            gs_cmd = [
                'gs',
                '-dNOPAUSE',
                '-dBATCH',
                '-dSAFER',
                '-sDEVICE=png16m',
                '-r300',  # 300 DPI
                '-dTextAlphaBits=4',  # Anti-aliasing for text
                '-dGraphicsAlphaBits=4',  # Anti-aliasing for graphics
                '-dEPSCrop',  # Crop to bounding box instead of full page
                f'-sOutputFile={output_file}',
                input_file
            ]
            
            result = subprocess.run(gs_cmd, capture_output=True, timeout=60)
            
            if result.returncode == 0 and os.path.exists(output_file):
                # Resize if too large (keeping quality)
                img = Image.open(output_file)
                if img.width > self.PREVIEW_MAX_WIDTH or img.height > self.PREVIEW_MAX_HEIGHT:
                    img.thumbnail((self.PREVIEW_MAX_WIDTH, self.PREVIEW_MAX_HEIGHT), Image.Resampling.LANCZOS)
                    img.save(output_file, 'PNG', quality=95)
                return True
            return False
        except Exception as e:
            st.warning(f"EPS/AI conversion failed: {str(e)}")
            return False
    
    def extract_pantone_colors(self, file_path):
        """Extract Pantone spot colors from vector file"""
        try:
            ext = Path(file_path).suffix.lower()
            
            # Only extract from AI/EPS/PDF/SVG
            if ext not in ['.ai', '.eps', '.pdf', '.svg']:
                return []
            
            # Read file content
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                    text = content.decode('latin-1', errors='ignore')
            except:
                return []
            
            import re
            
            # Look for Pantone color definitions
            pantone_patterns = [
                r'PANTONE\s+(\d+(?:-\d+)?)\s*([A-Z]{1,3})',  # PANTONE 293 U, etc.
                r'/\(PANTONE\s+(\d+(?:-\d+)?)\s*([A-Z]{1,3})\)',
                r'%%CMYKCustomColor:.*PANTONE\s+(\d+(?:-\d+)?)\s*([A-Z]{1,3})',
            ]
            
            pantone_set = set()
            for pattern in pantone_patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    number = match.group(1)
                    variant = match.group(2).upper()
                    pantone_name = f"PANTONE {number} {variant}"
                    pantone_set.add(pantone_name)
            
            return sorted(list(pantone_set))
        except:
            return []
    
    def generate_preview(self, input_file, bg_type='auto'):
        """Generate preview with all features"""
        ext = Path(input_file).suffix.lower()
        
        # Check if embroidery file
        if self.embroidery.is_embroidery_file(input_file):
            output_file = tempfile.mktemp(suffix='.png')
            success, info = self.embroidery.convert_to_png(input_file, output_file)
            
            if success:
                img = Image.open(output_file)
                return {
                    'image': output_file,
                    'width': img.width,
                    'height': img.height,
                    'file_type': 'embroidery',
                    'size_kb': round(os.path.getsize(output_file) / 1024, 2),
                    'embroidery_info': info
                }
            else:
                return None
        
        # Vector file processing
        output_file = tempfile.mktemp(suffix='.png')
        conversion_success = False
        
        # Try conversion based on file type
        if ext == '.svg':
            conversion_success = self._convert_svg_with_cairosvg(input_file, output_file)
        elif ext == '.pdf':
            conversion_success = self._convert_pdf_with_pdf2image(input_file, output_file)
        elif ext in ['.eps', '.ai']:
            conversion_success = self._convert_eps_ai_with_ghostscript(input_file, output_file)
        elif ext in ['.cdr', '.xcf']:
            st.error(f"{ext.upper()} files require desktop conversion tools. Please export as PDF or SVG.")
            return None
        
        if not conversion_success:
            st.error(f"Failed to convert {ext} file. Please try exporting as PDF or SVG.")
            return None
        
        # Extract Pantone colors
        pantone_colors = self.extract_pantone_colors(input_file)
        
        # Get image info
        img = Image.open(output_file)
        
        # Calculate physical size at 300 DPI
        width_inches = round(img.width / 300, 2)
        height_inches = round(img.height / 300, 2)
        
        result = {
            'image': output_file,
            'width': img.width,
            'height': img.height,
            'file_type': 'vector',
            'size_kb': round(os.path.getsize(output_file) / 1024, 2),
            'physical_size': {
                'width_inches': width_inches,
                'height_inches': height_inches,
                'dpi': 300
            }
        }
        
        # Add Pantone colors if found
        if pantone_colors:
            result['pantone_colors'] = pantone_colors
        
        return result


def save_as_pdf(image_path, output_pdf):
    """Convert preview image to PDF"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        
        img = Image.open(image_path)
        
        # Create PDF
        c = canvas.Canvas(output_pdf, pagesize=letter)
        
        # Calculate dimensions to fit on page
        page_width, page_height = letter
        margin = 50
        
        max_width = page_width - 2 * margin
        max_height = page_height - 2 * margin
        
        # Scale image to fit
        scale = min(max_width / img.width, max_height / img.height)
        new_width = img.width * scale
        new_height = img.height * scale
        
        # Center on page
        x = (page_width - new_width) / 2
        y = (page_height - new_height) / 2
        
        # Draw image
        c.drawImage(ImageReader(img), x, y, width=new_width, height=new_height)
        c.save()
        
        return True
    except Exception as e:
        st.error(f"PDF creation failed: {str(e)}")
        return False


# Main App
st.markdown('<h1 class="main-header">🎨 ArtCheck - IT WORKS!</h1>', unsafe_allow_html=True)
st.markdown('<p class="tagline">Vector & Embroidery File Preview Generator</p>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("💬 Ask Art Department")
    
    if st.button("📥 Submit Question", use_container_width=True):
        st.info("Feature coming soon! For now, check the FAQ below.")
    
    st.divider()
    
    st.markdown("**💡 Save your art team 15+ hours/week**")
    st.caption("Instant previews = fewer interruptions")

# File Upload Section
st.markdown("## 📁 Upload Your File")

vector_formats = ".ai, .eps, .pdf, .svg, .cdr, .xcf"
embroidery_formats = ".dst, .pes, .exp, .jef, .vp3, .xxx, .u01"

st.info(f"**Supported:** Vector files ({vector_formats}) | Embroidery files ({embroidery_formats})")

uploaded_file = st.file_uploader(
    "🎨 Drag and drop your file here or click to browse",
    type=['ai', 'eps', 'pdf', 'svg', 'cdr', 'xcf', 'indd', 'dst', 'pes', 'exp', 'jef', 'vp3', 'xxx', 'u01'],
    help="Supports vector and embroidery files up to 200MB"
)

if uploaded_file:
    # Check for InDesign files
    if uploaded_file.name.lower().endswith('.indd'):
        st.error("### 📄 InDesign Files Not Supported")
        st.warning("""
        **InDesign (.indd) files cannot be processed directly.**
        
        **Please export from InDesign as:**
        - **PDF** (File → Export → Adobe PDF) - BEST for print
        - **AI** (File → Export → Adobe Illustrator)
        - **EPS** (File → Export → EPS)
        
        Then upload the exported file to ArtCheck!
        """)
        st.stop()
    
    st.success(f"✓ Uploaded: **{uploaded_file.name}** ({uploaded_file.size / 1024 / 1024:.2f} MB)")
    
    # Background options
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        bg_auto = st.button("🔄 Auto", use_container_width=True)
    with col2:
        bg_light = st.button("☀️ Light", use_container_width=True)
    with col3:
        bg_dark = st.button("🌙 Dark", use_container_width=True)
    with col4:
        bg_transparent = st.button("⬜ Transparent", use_container_width=True)
    
    bg_type = 'auto'
    if bg_light:
        bg_type = 'light'
    elif bg_dark:
        bg_type = 'dark'
    elif bg_transparent:
        bg_type = 'transparent'
    
    # Generate Preview
    if st.button("🚀 Generate Preview", use_container_width=True, type="primary"):
        with st.spinner("Generating preview..."):
            # Save uploaded file to temp location
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name
            
            generator = PreviewGenerator()
            result = generator.generate_preview(tmp_path, bg_type)
            
            # Cleanup temp input
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            
            if result:
                st.markdown('<div class="success-box">✅ Preview generated successfully!</div>', 
                          unsafe_allow_html=True)
                
                # FILE TYPE BANNER
                if result.get('file_type') == 'vector':
                    st.markdown("""
                    <div style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); 
                                padding: 30px; 
                                border-radius: 15px; 
                                text-align: center;
                                margin: 20px 0;
                                border: 4px solid #11998e;">
                        <h1 style="color: white; margin: 0; font-size: 48px;">✅ VECTOR FILE</h1>
                        <p style="color: white; margin: 10px 0 0 0; font-size: 24px; font-weight: bold;">
                            Scalable • Print-Ready • High Quality
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                elif result.get('file_type') == 'embroidery':
                    st.markdown("""
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                                padding: 30px; 
                                border-radius: 15px; 
                                text-align: center;
                                margin: 20px 0;
                                border: 4px solid #667eea;">
                        <h1 style="color: white; margin: 0; font-size: 48px;">🧵 EMBROIDERY FILE</h1>
                        <p style="color: white; margin: 10px 0 0 0; font-size: 24px; font-weight: bold;">
                            Stitch Data • Production Ready
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Layout: Preview + Info
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.image(result['image'], caption="Your Preview", use_container_width=True)
                
                with col2:
                    st.markdown("### Preview Info")
                    st.metric("Dimensions", f"{result['width']} × {result['height']} px")
                    
                    # Physical size
                    if 'physical_size' in result:
                        phys = result['physical_size']
                        st.metric("Physical Size", f"{phys['width_inches']}\" × {phys['height_inches']}\"")
                        st.caption(f"At {phys['dpi']} DPI • Vector = scales to any size")
                    
                    st.metric("File Size", f"{result['size_kb']} KB")
                    st.metric("Background", bg_type.title())
                    
                    st.markdown("---")
                    
                    # PANTONE COLORS (only show if detected)
                    if 'pantone_colors' in result and result['pantone_colors']:
                        st.markdown("### 🎨 Pantone Spot Colors")
                        st.success(f"✓ **{len(result['pantone_colors'])} Pantone colors detected**")
                        for pantone in result['pantone_colors']:
                            st.markdown(f"### **{pantone}**")
                        st.markdown("")
                    
                    # Embroidery info
                    if 'embroidery_info' in result:
                        emb = result['embroidery_info']
                        st.markdown("### 🧵 Embroidery Info")
                        st.metric("Stitch Count", f"{emb['stitch_count']:,}")
                        st.metric("Thread Changes", emb['thread_changes'])
                        st.metric("Size", f"{emb['width_mm']}mm × {emb['height_mm']}mm")
                    
                    st.markdown("---")
                    
                    # Download buttons
                    st.markdown("### 📥 Download")
                    
                    # Download preview PNG
                    with open(result['image'], 'rb') as f:
                        st.download_button(
                            label="⬇️ Download Preview (PNG)",
                            data=f,
                            file_name=f"{Path(uploaded_file.name).stem}_preview.png",
                            mime="image/png",
                            use_container_width=True
                        )
                    
                    # Convert to PDF
                    if result.get('file_type') == 'vector':
                        if st.button("📄 Convert to PDF", use_container_width=True):
                            pdf_path = tempfile.mktemp(suffix='.pdf')
                            if save_as_pdf(result['image'], pdf_path):
                                with open(pdf_path, 'rb') as f:
                                    st.download_button(
                                        label="⬇️ Download PDF",
                                        data=f,
                                        file_name=f"{Path(uploaded_file.name).stem}.pdf",
                                        mime="application/pdf",
                                        use_container_width=True
                                    )
                                os.unlink(pdf_path)

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Built with ❤️ for promotional products professionals</p>
    <p>Save your art department 15+ hours per week</p>
</div>
""", unsafe_allow_html=True)
