"""
ArtCheck - Enhanced with Embroidery File Support + Ask ArtBot
Handles vector files AND embroidery files (.dst, .pes, .exp, etc.)
NOW WITH: AI-powered production artist assistant
CLOUD-OPTIMIZED VERSION - Uses CairoSVG, pdf2image, reportlab instead of Inkscape/ImageMagick
"""

import streamlit as st
import subprocess
import os
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import shutil
import tempfile
import json

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
    .artbot-answer {
        padding: 1.5rem;
        border-radius: 0.5rem;
        background: #f8f9fa;
        border-left: 4px solid #667eea;
        margin: 1rem 0;
        font-size: 1rem;
        line-height: 1.6;
    }
    .artbot-header {
        color: #667eea;
        font-weight: bold;
        font-size: 1.1rem;
        margin-bottom: 0.5rem;
    }
    section[data-testid="stSidebar"] * {
        font-size: 0.95rem !important;
    }
    section[data-testid="stSidebar"] .stButton button {
        font-size: 0.95rem !important;
    }
    section[data-testid="stSidebar"] .stTextInput input {
        font-size: 0.95rem !important;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# ARTBOT INTEGRATION
# ============================================================================

ARTBOT_SYSTEM_PROMPT = """You are ArtBot, a senior production artist with 20+ years of promotional products experience. You're like the veteran art department lead who sales reps message when they have a customer issue.

YOUR ROLE: Give sales reps EXACTLY what to say/do - not just technical info. You're their experienced colleague who's handled this situation 1,000 times before.

CRITICAL PRINCIPLE - TECHNICAL ACCURACY WITH COMMERCIAL REALITY:
Always be technically accurate (customers can Google/ask ChatGPT to verify), BUT frame answers around commercial practicality for promotional products vendors. Use this pattern: "YES, [X] is technically possible, BUT here's why most vendors don't offer it / here's the commercial reality / here's what actually works better in production."

Never say something CAN'T be done if it technically can - instead explain why it's not commonly offered and provide practical alternatives.

RESPONSE STRUCTURE - ALWAYS include these sections when relevant:

1. 📋 QUICK ANSWER (what's happening - be technically accurate)
2. 📧 CUSTOMER SCRIPT (exact words to use)
3. 💡 HOW TO EXPLAIN IT (customer-friendly language)
4. 🔍 WHAT TO CHECK (troubleshooting steps)
5. 💰 PRICING GUIDANCE (how to handle costs)
6. ⚠️ RED FLAGS (what to watch for)

CORE EXPERTISE:
- File format requirements for all decoration methods (screen printing, embroidery, DTG, laser engraving, pad printing, debossing, etc.)
- Vector vs raster - and how to explain this to customers who don't care about technical details
- Color management: Pantone matching, CMYK vs RGB, spot colors, and why "it looks different on my screen"
- Resolution requirements and how to handle low-res files
- File preparation issues and what causes art department rejections
- Embroidery specifics: stitch counts, thread colors, digitizing
- Screen printing: color separations, underbase, limitations
- Common customer objections and how to address them

DECORATION METHODS & CUSTOMER-FACING LANGUAGE:

Screen Printing:
- Tech: Spot colors, halftones, underbase, max 4-6 colors
- Customer: "Each color is a separate screen, which affects pricing. Complex designs with many colors work better with other methods."

Embroidery:
- Tech: Stitch files (.dst, .pes), 8k-12k stitch limit for left chest
- Customer: "Your logo needs to be converted to stitch data. More complex designs have higher stitch counts which increase cost and can cause fabric puckering."

DTG (Direct-to-Garment):
- Tech: Full color raster, 300 DPI minimum, white underbase
- Customer: "This prints like an inkjet printer directly on the shirt. Great for photos and complex designs, but works best on cotton and light colors."

CRITICAL: Frame technical issues as protecting the customer's brand quality, not as limitations.

Bad: "Your file won't work"
Good: "To ensure your logo looks sharp and professional on the final product, we need..."

EXAMPLES OF TECHNICAL ACCURACY + COMMERCIAL REALITY:

Example: "Can I embroider gradients?"
Bad Answer: "No, embroidery can't do gradients"
Good Answer: "Yes, gradient embroidery is technically possible using thread-blending or variegated thread techniques. However, most promotional products vendors don't offer this because it requires specialty digitizing ($75-150 setup), results can be inconsistent between production runs, and typically doubles the per-piece cost. Here are the alternatives that give you a premium look at better value: [options with pricing]"

Example: "Can I use RGB colors for print?"
Bad Answer: "No, you can't use RGB"
Good Answer: "RGB files will print, but the colors will shift significantly - bright RGB colors appear much duller in CMYK print. This isn't a limitation, it's physics: screens emit light (RGB) while printers absorb light with ink (CMYK). For accurate color matching, we need to convert to CMYK or use Pantone spot colors. Here's what to tell the customer: [script]"

Example: "Can we print 12 colors in screen printing?"
Bad Answer: "No, too many colors"
Good Answer: "Yes, 12-color screen printing is technically possible - each color just needs its own screen. However, the setup cost and per-piece price make it rarely practical for promotional products. Here's the pricing reality: [breakdown]. Most customers get better ROI with these alternatives: [options]"

HANDLING "BUT CHATGPT SAID..." SCENARIOS:
If a customer claims ChatGPT or Google says something is possible that you're recommending against, acknowledge the technical possibility FIRST, then explain the commercial reality. Never contradict easily verifiable information - instead add the context ChatGPT doesn't have (industry pricing, vendor capabilities, production practicalities).

HANDLING COMMON SCENARIOS:

🚫 Low Resolution File:
"That file will print blurry. Here's what to tell them:
📧 SCRIPT: 'Thanks for the logo! To ensure it looks crisp and professional on your [products], we need either a vector file (.ai, .eps, .pdf) or a high-resolution image (300 DPI at print size). Your current file is 72 DPI which will appear pixelated. Do you have the original design file from your designer? If not, our art team can recreate it for $[price].'
💰 PRICING: Don't waive art fees - position as quality assurance"

🎨 Too Many Colors:
"Design has 12 colors, screen printing max is typically 4-6. Here's the conversation:
📧 SCRIPT: 'Love the design! For screen printing, each color is a separate screen which affects pricing and production time. We can either simplify to 4-6 colors (I can get you a quote on that), or use digital printing which handles full color but at a different price point. Which direction works better for your budget?'
💡 EXPLAIN: Walk them through the cost difference - 6 color screen print vs DTG"

🧵 Wrong File for Embroidery:
"They sent a .jpg, need actual embroidery file:
📧 SCRIPT: 'For embroidery, we need the design converted into stitch data (.dst file) by a digitizer. If you have an embroidery file from a previous order, we can use that. Otherwise, our digitizing service is $[price] - one-time setup fee, then you own the file for future orders.'
💰 PRICING: Digitizing $25-50 typical, charge what your supplier charges + markup"

💸 Customer Balking at Art Charges:
"They're upset about $35 art fee:
📧 SCRIPT: 'I totally understand wanting to keep costs down. The art setup ensures your logo is print-ready and will look professional on every piece. Think of it like a one-time investment - once we have your file properly set up, there's no art charge on reorders. Plus, we're essentially protecting your brand's image quality.'
💡 FRAME: It's quality control, not an upcharge. Compare to getting cheap business cards that look blurry."

COMMUNICATION STYLE:
- Lead with the customer-facing script - that's what the rep needs immediately
- Use "Here's what to tell them:" before scripts
- Include pricing guidance (reps need to know if they can negotiate)
- Give the "why" in customer-friendly language (not technical jargon)
- Point out upsell opportunities when relevant
- Warn about common customer objections

AVOID:
- Don't just say "they need 300 DPI" - give them the WORDS to explain why
- Don't give tech specs without context about impact on timeline/cost
- Don't assume the sales rep knows how to handle pushback
- Don't leave pricing ambiguous - give ranges or tell them to check with production

Remember: You're not just answering technical questions - you're coaching sales reps through customer conversations. Give them confidence, scripts, and the reasoning to back it up."""

def ask_artbot(question, conversation_history=None):
    """
    Call Claude API to answer production questions
    
    Args:
        question: User's question
        conversation_history: Optional list of previous messages for context
    
    Returns:
        str: ArtBot's answer
    """
    try:
        # Build messages array
        messages = []
        
        # Add conversation history if exists
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current question
        messages.append({
            "role": "user",
            "content": question
        })
        
        # Note: In production Streamlit Cloud, you'd use st.secrets for the API key
        # For now, this shows the structure - API key would come from environment
        # The actual API call would happen here, but since we can't make external
        # API calls in this demo, we'll return a helpful message
        
        # This is where the actual API call would be:
        # client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
        # response = client.messages.create(
        #     model="claude-sonnet-4-20250514",
        #     max_tokens=1000,
        #     system=ARTBOT_SYSTEM_PROMPT,
        #     messages=messages
        # )
        # return response.content[0].text
        
        # For demo purposes, return a template answer
        return f"""I'm ArtBot, your production assistant! 🤖

To activate me, you'll need to:
1. Add your Anthropic API key to Streamlit secrets
2. Install the `anthropic` package
3. Uncomment the API call in the code

Once set up, I can answer questions like:
- "What file format do I need for screen printing?"
- "How many colors can embroidery handle?"
- "Why is my Pantone color wrong?"
- "What DPI for a 2 inch logo?"

Your question: "{question}"

*This is a demo response. Configure API key to enable full functionality.*"""
        
    except Exception as e:
        return f"⚠️ ArtBot error: {str(e)}\n\nPlease check your API configuration."


# ============================================================================
# ORIGINAL ARTCHECK CODE (Embroidery + Vector handling)
# ============================================================================

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

        try:
            import fitz  # PyMuPDF
            self.fitz = fitz
            self.has_fitz = True
        except ImportError:
            self.fitz = None
            self.has_fitz = False
    
    def is_supported(self, filename):
        """Check if file format is supported"""
        ext = Path(filename).suffix.lower()
        return ext in self.SUPPORTED_FORMATS or self.embroidery.is_embroidery_file(filename)
    
    def _svg_has_embedded_raster(self, input_file):
        """Detect if SVG is just a wrapper around an embedded raster image"""
        try:
            with open(input_file, 'r', errors='ignore') as f:
                content = f.read(4000)  # Check first 4KB
            # SVGs with embedded rasters typically have base64 image data or xlink:href to raster
            import re
            has_image_tag = bool(re.search(r'<image', content, re.IGNORECASE))
            has_base64 = 'base64' in content
            # Check if there are almost no path/shape elements (pure raster wrapper)
            has_paths = bool(re.search(r'<(path|rect|circle|ellipse|line|polyline|polygon)', content, re.IGNORECASE))
            return has_image_tag and (has_base64 or not has_paths)
        except Exception:
            return False

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

    def _convert_eps_with_ghostscript(self, input_file, output_file):
        """Convert EPS to PNG using Ghostscript"""
        try:
            cmd = [
                'gs', '-dNOPAUSE', '-dBATCH', '-dSAFER',
                '-sDEVICE=pngalpha',
                '-r300',
                '-dEPSCrop',
                f'-sOutputFile={output_file}',
                input_file
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return True
            # Try without EPSCrop if that failed
            cmd2 = [
                'gs', '-dNOPAUSE', '-dBATCH', '-dSAFER',
                '-sDEVICE=pngalpha',
                '-r300',
                f'-sOutputFile={output_file}',
                input_file
            ]
            result2 = subprocess.run(cmd2, capture_output=True, timeout=30)
            return result2.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception as e:
            st.warning(f"Ghostscript EPS conversion failed: {str(e)}")
            return False

    def _convert_with_fitz(self, input_file, output_file):
        """Convert PDF or SVG to PNG using PyMuPDF (fitz) - handles AI-native PDFs"""
        if not self.has_fitz:
            return False
        try:
            doc = self.fitz.open(input_file)
            page = doc[0]
            # Calculate scale to ensure minimum 1200px on longest side
            rect = page.rect
            longest = max(rect.width, rect.height)
            scale = max(10, 1200 / longest)  # At least 10x, enough to hit 1200px
            mat = self.fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=True)
            pix.save(output_file)
            doc.close()
            return os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception as e:
            st.warning(f"PyMuPDF conversion failed: {str(e)}")
            return False

    def _apply_background(self, output_file, bg_type):
        """Apply background color to a PNG preview"""
        try:
            img = Image.open(output_file).convert('RGBA')

            if bg_type == 'transparent':
                # Keep as-is, just save as RGBA PNG
                img.save(output_file, 'PNG')
                return

            # Determine background color
            if bg_type == 'dark':
                bg_color = (30, 30, 30, 255)
            elif bg_type == 'light':
                bg_color = (255, 255, 255, 255)
            elif bg_type == 'auto':
                # Check if artwork is mostly light — if so, use dark bg
                grayscale = img.convert('L')
                avg = sum(grayscale.getdata()) / len(grayscale.getdata())
                bg_color = (30, 30, 30, 255) if avg > 200 else (255, 255, 255, 255)
            else:
                bg_color = (255, 255, 255, 255)

            background = Image.new('RGBA', img.size, bg_color)
            background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
            background.convert('RGB').save(output_file, 'PNG')
        except Exception as e:
            st.warning(f"Background application failed: {str(e)}")

    def _detect_file_type_label(self, input_file, ext):
        """Return accurate file type label"""
        if ext == '.svg' and self._svg_has_embedded_raster(input_file):
            return 'SVG (embedded raster)'
        elif ext == '.eps':
            return 'Vector (EPS)'
        elif ext == '.ai':
            return 'Vector (AI)'
        elif ext == '.pdf':
            return 'Vector (PDF)'
        return 'Vector'

    def generate_preview(self, input_file, bg_type='auto'):
        """Generate preview from vector or embroidery file"""
        ext = Path(input_file).suffix.lower()
        
        # Handle embroidery files
        if self.embroidery.is_embroidery_file(input_file):
            output_file = tempfile.mktemp(suffix='.png')
            success, result = self.embroidery.convert_to_png(input_file, output_file)
            
            if success:
                self._apply_background(output_file, bg_type)
                img = Image.open(output_file)
                return {
                    'image': output_file,
                    'width': img.width,
                    'height': img.height,
                    'size_kb': round(os.path.getsize(output_file) / 1024, 2),
                    'file_type': 'embroidery',
                    'embroidery_info': result
                }
            else:
                st.error(f"Embroidery conversion failed: {result}")
                return None
        
        output_file = tempfile.mktemp(suffix='.png')
        success = False
        file_type_label = self._detect_file_type_label(input_file, ext)

        if ext == '.eps':
            # EPS: Ghostscript first, then fitz as fallback
            success = self._convert_eps_with_ghostscript(input_file, output_file)
            if not success:
                success = self._convert_with_fitz(input_file, output_file)

        elif ext == '.pdf' or ext == '.ai':
            # PDF/AI: fitz first, pdf2image as fallback
            success = self._convert_with_fitz(input_file, output_file)
            if not success and self.has_pdf2image:
                try:
                    pages = self.pdf2image_convert(input_file, first_page=1, last_page=1, dpi=150)
                    if pages:
                        pages[0].save(output_file, 'PNG')
                        success = os.path.exists(output_file) and os.path.getsize(output_file) > 0
                except Exception as e:
                    st.warning(f"pdf2image fallback failed: {str(e)}")

        elif ext == '.svg':
            embedded_raster = self._svg_has_embedded_raster(input_file)
            if embedded_raster:
                # Try fitz first for raster-in-SVG, then CairoSVG
                success = self._convert_with_fitz(input_file, output_file)
            if not success:
                success = self._convert_svg_with_cairosvg(input_file, output_file)
            if not success and self.has_fitz:
                success = self._convert_with_fitz(input_file, output_file)

        if success and os.path.exists(output_file):
            self._apply_background(output_file, bg_type)
            img = Image.open(output_file)
            return {
                'image': output_file,
                'width': img.width,
                'height': img.height,
                'size_kb': round(os.path.getsize(output_file) / 1024, 2),
                'file_type': file_type_label
            }

        st.error("Could not convert file. Please try exporting as PDF or SVG from your design application.")
        return None



# ============================================================================
# COLOR EXTRACTOR - Reads vector color data from source files
# ============================================================================


# ============================================================================
# RASTER ANALYZER - Handles PNG/JPG/GIF/TIFF/BMP/WEBP uploads
# ============================================================================

class RasterAnalyzer:
    """Analyzes raster image files for production suitability"""

    RASTER_FORMATS = ['.png', '.jpg', '.jpeg', '.gif', '.tiff', '.tif', '.bmp', '.webp']

    def is_raster(self, filename):
        return Path(filename).suffix.lower() in self.RASTER_FORMATS

    def analyze(self, input_file):
        """
        Returns dict with:
          width_px, height_px, dpi, color_mode,
          print_sizes, verdict, warnings, recommendations
        """
        results = {
            'width_px': 0, 'height_px': 0,
            'dpi': 72, 'color_mode': 'Unknown',
            'print_sizes': {}, 'verdict': 'unknown',
            'warnings': [], 'recommendations': []
        }
        try:
            img = Image.open(input_file)
            results['width_px'] = img.width
            results['height_px'] = img.height
            results['color_mode'] = img.mode

            # Get DPI from image metadata
            dpi_info = img.info.get('dpi') or img.info.get('jfif_density')
            if dpi_info and isinstance(dpi_info, tuple):
                dpi = round(max(dpi_info[0], dpi_info[1]))
            elif dpi_info and isinstance(dpi_info, (int, float)):
                dpi = round(dpi_info)
            else:
                dpi = 72  # Default assumption for web images

            # Clamp to realistic range
            if dpi < 1 or dpi > 2400:
                dpi = 72
            results['dpi'] = dpi

            # Calculate usable print sizes
            w_at_300 = round(img.width / 300, 2)
            h_at_300 = round(img.height / 300, 2)
            w_at_150 = round(img.width / 150, 2)
            h_at_150 = round(img.height / 150, 2)
            w_at_200 = round(img.width / 200, 2)
            h_at_200 = round(img.height / 200, 2)

            results['print_sizes'] = {
                '300dpi': (w_at_300, h_at_300),   # Screen print, embroidery digitizing
                '200dpi': (w_at_200, h_at_200),   # Acceptable quality
                '150dpi': (w_at_150, h_at_150),   # DTG minimum
            }

            # Determine production verdict
            max_dim = max(img.width, img.height)
            if dpi >= 300 or (img.width >= 1200 and img.height >= 1200):
                results['verdict'] = 'good'
            elif dpi >= 150 or max_dim >= 800:
                results['verdict'] = 'marginal'
            else:
                results['verdict'] = 'poor'

            # Generate warnings
            if dpi <= 72:
                results['warnings'].append("⚠️ 72 DPI detected — this file was likely saved from a website or screen capture")
            if results['verdict'] == 'poor':
                results['warnings'].append("❌ Resolution too low for most decoration methods — will print blurry")
            elif results['verdict'] == 'marginal':
                results['warnings'].append("⚠️ Marginal resolution — may be acceptable for DTG or small print sizes only")

            if img.mode == 'RGB':
                results['warnings'].append("⚠️ RGB color mode — will need conversion to CMYK for most print methods")
            elif img.mode == 'RGBA':
                results['warnings'].append("ℹ️ Image has transparency (alpha channel)")
            elif img.mode == 'P':
                results['warnings'].append("⚠️ Indexed/palette color mode — may have limited colors")

            # Recommendations
            if results['verdict'] in ('poor', 'marginal'):
                results['recommendations'].append("Ask the customer for the original vector file (.ai, .eps, .pdf) from their designer")
                results['recommendations'].append("If no vector exists, ask for the highest-resolution version available (original camera photo, original design file)")
                if dpi <= 72:
                    results['recommendations'].append("Do NOT use this file — it was saved from a website at screen resolution")
            if img.mode == 'RGB':
                results['recommendations'].append("Convert to CMYK in Illustrator or Photoshop before sending to production")

        except Exception as e:
            results['warnings'].append(f"Could not analyze image: {str(e)}")

        return results


def render_raster_results(analysis, filename):
    """Display raster analysis results"""
    verdict = analysis.get('verdict', 'unknown')
    dpi = analysis.get('dpi', 72)
    w, h = analysis.get('width_px', 0), analysis.get('height_px', 0)
    sizes = analysis.get('print_sizes', {})

    # Verdict banner
    if verdict == 'good':
        st.markdown('''<div style="padding:12px;border-radius:8px;background:#1a6b3a;color:#fff;font-size:1rem;font-weight:bold;margin-bottom:12px;">✅ Production Ready — Resolution is sufficient</div>''', unsafe_allow_html=True)
    elif verdict == 'marginal':
        st.markdown('''<div style="padding:12px;border-radius:8px;background:#7d5a00;color:#fff;font-size:1rem;font-weight:bold;margin-bottom:12px;">⚠️ Marginal Quality — Use with caution</div>''', unsafe_allow_html=True)
    else:
        st.markdown('''<div style="padding:12px;border-radius:8px;background:#8b1a1a;color:#fff;font-size:1rem;font-weight:bold;margin-bottom:12px;">❌ Not Suitable for Production — Resolution too low</div>''', unsafe_allow_html=True)

    # Image stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Dimensions", f"{w} × {h} px")
    with col2:
        st.metric("DPI (metadata)", f"{dpi} DPI")
    with col3:
        st.metric("Color Mode", analysis.get('color_mode', 'Unknown'))

    # Print size table
    if sizes:
        st.markdown("**📐 Usable Print Sizes:**")
        size_300 = sizes.get('300dpi', (0, 0))
        size_200 = sizes.get('200dpi', (0, 0))
        size_150 = sizes.get('150dpi', (0, 0))
        st.markdown(f"""
| Quality | DPI | Max Print Size | Suitable For |
|---------|-----|----------------|-------------|
| High | 300 | {size_300[0]}" × {size_300[1]}" | Screen print, laser, pad print |
| Acceptable | 200 | {size_200[0]}" × {size_200[1]}" | Most methods at smaller sizes |
| Minimum | 150 | {size_150[0]}" × {size_150[1]}" | DTG only |
""")

    # Warnings
    if analysis.get('warnings'):
        for w in analysis['warnings']:
            st.warning(w)

    # Recommendations
    if analysis.get('recommendations'):
        st.markdown("**💡 What to do:**")
        for r in analysis['recommendations']:
            st.markdown(f"• {r}")

class ColorExtractor:
    """Extracts fill and stroke colors from vector files before rasterization"""

    def extract(self, input_file):
        """
        Main entry point. Returns dict with:
          fills, strokes, spot_colors, gradients, warnings
        """
        ext = Path(input_file).suffix.lower()
        results = {
            'fills': [],
            'strokes': [],
            'spot_colors': [],
            'gradients': [],
            'warnings': [],
            'color_space': None
        }

        if ext in ['.pdf', '.ai']:
            return self._extract_from_pdf(input_file, results)
        elif ext == '.eps':
            return self._extract_from_eps(input_file, results)
        elif ext == '.svg':
            return self._extract_from_svg(input_file, results)
        else:
            results['warnings'].append("Color extraction not supported for this file type.")
            return results

    def _cmyk_to_hex(self, c, m, y, k):
        """Convert CMYK (0-1) to hex for display swatch"""
        r = int(255 * (1 - c) * (1 - k))
        g = int(255 * (1 - m) * (1 - k))
        b = int(255 * (1 - y) * (1 - k))
        return f'#{r:02x}{g:02x}{b:02x}', (r, g, b)

    def _rgb_to_hex(self, r, g, b):
        ri, gi, bi = int(r*255), int(g*255), int(b*255)
        return f'#{ri:02x}{gi:02x}{bi:02x}', (ri, gi, bi)

    def _format_cmyk(self, c, m, y, k):
        return f"C:{round(c*100)}% M:{round(m*100)}% Y:{round(y*100)}% K:{round(k*100)}%"

    def _extract_from_pdf(self, input_file, results):
        """Extract colors from PDF/AI using PyMuPDF"""
        try:
            import fitz
            doc = fitz.open(input_file)
            page = doc[0]

            fills = {}
            strokes = {}
            spot_colors = {}
            gradients = []

            # Get color space info
            try:
                page_dict = page.get_text("dict")
                results['color_space'] = 'CMYK/Mixed'
            except:
                pass

            # Extract via drawings (paths with fill/stroke info)
            # Detect document color mode
            results['color_mode'] = self._detect_color_mode_pdf(input_file)

            drawings = page.get_drawings()
            for drawing in drawings:
                # Fill color
                if drawing.get('fill') is not None:
                    fill = drawing['fill']
                    fill_cs = drawing.get('fill_opacity', 1.0)
                    opacity = round(fill_cs * 100) if fill_cs <= 1.0 else 100

                    if len(fill) == 4:  # CMYK
                        c, m, y, k = fill
                        label = self._format_cmyk(c, m, y, k)
                        hex_val, rgb = self._cmyk_to_hex(c, m, y, k)
                        key = label
                        if key not in fills:
                            fills[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                         'space': 'CMYK', 'opacity': opacity,
                                         'raw': (c, m, y, k)}
                    elif len(fill) == 3:  # fitz returns RGB for CMYK docs too — skip
                        # RGB fills from fitz are unreliable for production use.
                        # We only store them if we have no better data (handled after loop).
                        r, g, b = fill
                        label = f"R:{round(r*255)} G:{round(g*255)} B:{round(b*255)}"
                        hex_val, rgb_val = self._rgb_to_hex(r, g, b)
                        key = label
                        if key not in fills:
                            fills[key] = {'label': label, 'hex': hex_val, 'rgb': rgb_val,
                                         'space': 'RGB', 'opacity': opacity}
                    elif len(fill) == 1:  # Grayscale
                        gray = fill[0]
                        k_pct = round((1 - gray) * 100)
                        label = f"K:{k_pct}% (Black {k_pct}%)"
                        hex_val, rgb = self._cmyk_to_hex(0, 0, 0, 1-gray)
                        key = label
                        if key not in fills:
                            fills[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                         'space': 'Grayscale', 'opacity': opacity,
                                         'raw': (0, 0, 0, 1-gray)}

                # Stroke color
                if drawing.get('color') is not None:
                    stroke = drawing['color']
                    width = round(drawing.get('width', 1), 2)

                    if len(stroke) == 4:  # CMYK
                        c, m, y, k = stroke
                        label = self._format_cmyk(c, m, y, k)
                        hex_val, rgb = self._cmyk_to_hex(c, m, y, k)
                        key = f"{label}|{width}"
                        if key not in strokes:
                            strokes[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                           'space': 'CMYK', 'width': width,
                                           'raw': (c, m, y, k)}
                    elif len(stroke) == 3:
                        r, g, b = stroke
                        label = f"R:{round(r*255)} G:{round(g*255)} B:{round(b*255)}"
                        hex_val, rgb_val = self._rgb_to_hex(r, g, b)
                        key = f"{label}|{width}"
                        if key not in strokes:
                            strokes[key] = {'label': label, 'hex': hex_val, 'rgb': rgb_val,
                                           'space': 'RGB', 'width': width}
                    elif len(stroke) == 1:
                        gray = stroke[0]
                        k_pct = round((1 - gray) * 100)
                        label = f"K:{k_pct}% (Black {k_pct}%)"
                        hex_val, rgb = self._cmyk_to_hex(0, 0, 0, 1-gray)
                        key = f"{label}|{width}"
                        if key not in strokes:
                            strokes[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                           'space': 'Grayscale', 'width': width}

                # Detect gradients (shading)
                if drawing.get('type') == 'sh':
                    gradients.append({'type': 'gradient', 'label': 'Gradient detected'})

            doc.close()

            # Scan ALL xref objects for spot color / Separation definitions
            # This is where Pantone names live in Illustrator-generated PDFs
            try:
                import re
                doc2 = fitz.open(input_file)
                for xref in range(1, doc2.xref_count()):
                    try:
                        obj_str = doc2.xref_object(xref)
                        if not obj_str:
                            continue
                        # /Separation colorspace with name
                        sep_paren = re.findall(r'/Separation\s*\(([^)]+)\)', obj_str)
                        sep_slash = re.findall(r'/Separation\s*/([^\s/\[\]<>()]+)', obj_str)
                        for name in sep_paren + sep_slash:
                            name = name.strip()
                            if name and name not in ('All', 'None', 'Black', 'White', 'Cyan', 'Magenta', 'Yellow'):
                                spot_colors[name] = {'label': name, 'type': 'spot'}
                        # Also catch PANTONE anywhere in obj string
                        pantone_hits = re.findall(r'(PANTONE[^/\(\)\[\]<>\n]{1,40})', obj_str)
                        for ph in pantone_hits:
                            ph = ph.strip().strip('"-\'')
                            if ph and ph not in spot_colors:
                                spot_colors[ph] = {'label': ph, 'type': 'spot'}
                    except:
                        pass
                doc2.close()
            except:
                pass

            # Fallback: raw byte scan for PANTONE names in case xref missed them
            # AI files often embed Pantone names in compressed PostScript streams
            if not spot_colors:
                try:
                    import re
                    with open(input_file, 'rb') as f:
                        raw = f.read()
                    raw_text = raw.decode('latin-1', errors='ignore')
                    # Match PANTONE names like 'PANTONE 293 U' or 'PANTONE 1235 C'
                    raw_hits = re.findall(r'PANTONE\s+[\w.]+(?:\s+[\w.]+){0,3}', raw_text)
                    seen = set()
                    for hit in raw_hits:
                        hit = hit.strip()
                        # Clean up trailing junk
                        hit = re.sub(r'\s+[a-z]{5,}.*$', '', hit).strip()
                        if hit and hit not in seen and len(hit) < 40:
                            seen.add(hit)
                            spot_colors[hit] = {'label': hit, 'type': 'spot'}
                except:
                    pass

            # Raw PostScript CMYK scan — fallback when fitz only returns RGB
            # For CMYK docs, parse the content stream directly for k (black tint) and
            # setcmykcolor values which give us the real CMYK values
            if not spot_colors and not any(v.get('space') == 'CMYK' for v in fills.values()):
                try:
                    import re
                    with open(input_file, 'rb') as f:
                        raw = f.read()
                    raw_text = raw.decode('latin-1', errors='ignore')

                    # CMYK values: 0 0 0 0.4 k or 0 0 0 0.4 K (black tint)
                    k_hits = re.findall(r'0\s+0\s+0\s+([\d.]+)\s+[kK]', raw_text)
                    cmyk_hits = re.findall(r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+k', raw_text)

                    seen_k = set()
                    for k_val in k_hits:
                        k = float(k_val)
                        if k <= 0 or k > 1: continue
                        k_pct = round(k * 100)
                        label = f"K:{k_pct}% (Black {k_pct}%)"
                        if label not in seen_k:
                            seen_k.add(label)
                            hex_val, rgb_val = self._cmyk_to_hex(0, 0, 0, k)
                            fills[label] = {'label': label, 'hex': hex_val, 'rgb': rgb_val,
                                           'space': 'CMYK', 'opacity': 100}

                    for match in cmyk_hits:
                        c, m, y, k = [float(x) for x in match]
                        if self._is_registration_color(c, m, y, k): continue
                        label = self._format_cmyk(c, m, y, k)
                        if label not in fills:
                            hex_val, rgb_val = self._cmyk_to_hex(c, m, y, k)
                            fills[label] = {'label': label, 'hex': hex_val, 'rgb': rgb_val,
                                           'space': 'CMYK', 'opacity': 100}
                except:
                    pass

            # Suppress RGB fills when we have better color data:
            # - If spot colors found: RGB are fitz approximations, useless
            # - If doc is CMYK: RGB are fitz conversions, misleading
            # RGB fills only shown if doc is genuinely RGB with no spot/CMYK data
            color_mode = results.get('color_mode', 'Unknown')
            suppress_rgb = spot_colors or ('CMYK' in color_mode and 'RGB' not in color_mode) or any(v.get('space') == 'CMYK' for v in fills.values())
            if suppress_rgb:
                fills = {k: v for k, v in fills.items() if v.get('space') != 'RGB'}
                strokes = {k: v for k, v in strokes.items() if v.get('space') != 'RGB'}

            results['fills'] = list(fills.values())
            results['strokes'] = list(strokes.values())
            results['strokes'] = list(strokes.values())
            results['spot_colors'] = list(spot_colors.values())
            results['gradients'] = gradients

            # Generate warnings
            if gradients:
                results['warnings'].append("⚠️ Gradient detected — not compatible with screen print or embroidery")
            
            hairlines = [s for s in results['strokes'] if s.get('width', 1) < 0.5]
            if hairlines:
                results['warnings'].append("⚠️ Hairline stroke detected — may not reproduce in embroidery or laser engraving")

            total_colors = len(results['fills']) + len(results['spot_colors'])
            if total_colors > 6:
                results['warnings'].append(f"⚠️ {total_colors} colors detected — screen printing typically supports 4-6 colors max")

            # Detect mixed color spaces
            spaces = set(f.get('space') for f in results['fills'])
            if len(spaces) > 1:
                results['warnings'].append("⚠️ Mixed color spaces detected — verify consistency before production")

            return results

        except Exception as e:
            results['warnings'].append(f"Color extraction error: {str(e)}")
            return results

    def _is_registration_color(self, c, m, y, k):
        """Filter out pure primaries and registration artifacts"""
        vals = (round(c,1), round(m,1), round(y,1), round(k,1))
        artifacts = [
            (1,0,0,0), (0,1,0,0), (0,0,1,0), (0,0,0,1),  # pure primaries
            (1,1,1,1),  # registration black
            (0,0,0,0),  # paper white
        ]
        return vals in artifacts

    def _extract_from_eps(self, input_file, results):
        """Extract colors from EPS by parsing PostScript"""
        try:
            with open(input_file, 'r', errors='ignore') as f:
                content = f.read(50000)

            import re
            fills = {}
            strokes = {}
            spot_colors = {}

            # Detect document color mode
            results['color_mode'] = self._detect_color_mode_eps(input_file)

            # Spot colors first — if spot colors found, skip CMYK artifacts
            spot_patterns = re.findall(r'\(([^)]*(?:PANTONE|Pantone|PMS)[^)]*)\)', content)
            for sp in spot_patterns:
                sp = sp.strip()
                if sp:
                    spot_colors[sp] = {'label': sp, 'type': 'spot'}

            has_spots = len(spot_colors) > 0

            # CMYK - only include if not registration artifacts
            cmyk_patterns = re.findall(
                r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(?:setcmykcolor)', content)
            for match in cmyk_patterns:
                c, m, y, k = [float(x) for x in match]
                # Skip registration artifacts and pure primaries
                if self._is_registration_color(c, m, y, k):
                    continue
                # Skip K-only colors if we already have spot colors (likely tint of spot)
                if has_spots and c == 0 and m == 0 and y == 0:
                    continue
                label = self._format_cmyk(c, m, y, k)
                hex_val, rgb = self._cmyk_to_hex(c, m, y, k)
                fills[label] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                               'space': 'CMYK', 'opacity': 100}

            # Grayscale - only if no spots detected
            if not has_spots:
                gray_patterns = re.findall(r'([\d.]+)\s+setgray', content)
                for g in gray_patterns:
                    gray = float(g)
                    if gray in [0.0, 1.0]:  # Skip pure black/white artifacts
                        continue
                    k_pct = round((1 - gray) * 100)
                    label = f"K:{k_pct}% (Black {k_pct}%)"
                    hex_val, rgb = self._cmyk_to_hex(0, 0, 0, 1-gray)
                    fills[label] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                   'space': 'Grayscale', 'opacity': 100}

            results['spot_colors'] = list(spot_colors.values())

            if not results['fills'] and not results['spot_colors']:
                results['warnings'].append("Could not extract color data from this EPS file.")

            total_colors = len(results['fills']) + len(results['spot_colors'])
            if total_colors > 6:
                results['warnings'].append(f"⚠️ {total_colors} colors detected — screen printing typically supports 4-6 colors max")

            return results
        except Exception as e:
            results['warnings'].append(f"EPS color extraction error: {str(e)}")
            return results

    def _detect_color_mode_pdf(self, input_file):
        """Detect document color mode from PDF/AI xref objects + full raw byte scan"""
        has_cmyk = False
        has_rgb = False
        has_spot = False
        try:
            import fitz
            doc = fitz.open(input_file)
            for xref in range(1, min(doc.xref_count(), 500)):
                try:
                    obj = doc.xref_object(xref)
                    if '/DeviceCMYK' in obj: has_cmyk = True
                    if '/DeviceRGB' in obj: has_rgb = True
                    if '/Separation' in obj or 'PANTONE' in obj: has_spot = True
                except: pass
            try:
                page = doc[0]
                for d in page.get_drawings():
                    fill = d.get('fill') or []
                    if len(fill) == 4: has_cmyk = True
                    if len(fill) == 3: has_rgb = True
            except: pass
            doc.close()
        except: pass
        try:
            # Full file raw scan — read entire file for keyword detection
            with open(input_file, 'rb') as f:
                raw = f.read().decode('latin-1', errors='ignore')
            if 'PANTONE' in raw or '/Separation' in raw: has_spot = True
            if 'DeviceCMYK' in raw or 'setcmykcolor' in raw: has_cmyk = True
            if 'DeviceRGB' in raw or 'setrgbcolor' in raw: has_rgb = True
        except: pass
        if has_spot and has_cmyk: return 'Spot + CMYK'
        if has_spot: return 'Spot Color'
        if has_cmyk and has_rgb: return 'Mixed (CMYK + RGB)'
        if has_cmyk: return 'CMYK'
        if has_rgb: return 'RGB'
        return 'Unknown'

    def _detect_color_mode_eps(self, input_file):
        """Detect document color mode from EPS file"""
        has_spot = False
        has_cmyk = False
        has_rgb = False
        try:
            import re
            with open(input_file, 'r', errors='ignore') as f:
                full = f.read()
            if re.search(r'PANTONE|Separation', full): has_spot = True
            if re.search(r'setcmykcolor|DeviceCMYK|CMYKCustomColor', full): has_cmyk = True
            if re.search(r'setrgbcolor|DeviceRGB', full): has_rgb = True
        except: pass
        if has_spot and has_cmyk: return 'Spot + CMYK'
        if has_spot: return 'Spot Color'
        if has_cmyk: return 'CMYK'
        if has_rgb: return 'RGB'
        return 'Unknown'

    def _detect_color_mode_svg(self, content):
        """Detect color mode from SVG content"""
        import re
        has_pantone = bool(re.search(r'pantone|PANTONE', content, re.IGNORECASE))
        has_icc_cmyk = 'icc-color' in content and 'cmyk' in content.lower()
        has_hex = bool(re.search(r'#[0-9a-fA-F]{3,6}', content))
        if has_pantone: return 'Spot Color'
        if has_icc_cmyk: return 'CMYK'
        if has_hex: return 'RGB'
        return 'Unknown'

    def _extract_from_svg(self, input_file, results):
        """Extract colors from SVG by parsing XML"""
        try:
            import re
            with open(input_file, 'r', errors='ignore') as f:
                content = f.read()

            fills = {}
            strokes = {}
            spot_colors = {}

            results['color_mode'] = self._detect_color_mode_svg(content)

            # Spot colors — Pantone names in id attributes or content
            pantone_hits = re.findall(r'(?:PANTONE|Pantone)[^\s<>/]{1,40}', content)
            for ph in pantone_hits:
                ph = ph.strip().strip("\"-'")
                if ph:
                    spot_colors[ph] = {'label': ph, 'type': 'spot'}

            named_colors = []  # covered by pantone_hits above
            for nc in named_colors:
                nc = nc.replace('-', ' ').strip()
                if nc not in spot_colors:
                    spot_colors[nc] = {'label': nc, 'type': 'spot'}

            fill_matches = re.findall(r'fill[\s:="\']+([#][0-9a-fA-F]{3,6})', content)
            stroke_matches = re.findall(r'stroke[\s:="\']+([#][0-9a-fA-F]{3,6})', content)
            stroke_widths = re.findall(r'stroke-width[\s:="\']+([\d.]+)', content)

            has_spots = len(spot_colors) > 0
            artifact_hex = {'#ffffff', '#000000', '#FFFFFF', '#000000'}

            for val in fill_matches:
                if has_spots and val.lower() in artifact_hex:
                    continue
                fills[val] = {'label': val.upper(), 'hex': val, 'space': 'RGB', 'opacity': 100}

            avg_width = sum(float(w) for w in stroke_widths) / len(stroke_widths) if stroke_widths else 1.0
            for val in stroke_matches:
                if has_spots and val.lower() in artifact_hex:
                    continue
                strokes[val] = {'label': val.upper(), 'hex': val, 'space': 'RGB',
                               'width': avg_width, 'opacity': 100}

            results['fills'] = list(fills.values())
            results['strokes'] = list(strokes.values())
            results['spot_colors'] = list(spot_colors.values())

            if not results['fills'] and not results['spot_colors']:
                results['warnings'].append("Could not extract color data from this SVG.")

            total = len(results['fills']) + len(results['spot_colors'])
            if total > 6:
                results['warnings'].append(f"⚠️ {total} colors detected — screen printing typically supports 4-6 colors max")

            return results
        except Exception as e:
            results['warnings'].append(f"SVG color extraction error: {str(e)}")
            return results



def render_color_results(color_data, file_ext):
    """Render color extraction results in Streamlit"""
    if not color_data:
        return

    st.markdown("---")
    st.markdown("### 🎨 Color Analysis")

    has_anything = (color_data.get('spot_colors') or color_data.get('fills') or
                   color_data.get('strokes') or color_data.get('gradients'))

    if not has_anything and not color_data.get('warnings'):
        st.info("No color data extracted from this file.")
        return

    # Document color mode badge
    color_mode = color_data.get('color_mode')
    if color_mode:
        is_warning = 'RGB' in color_mode and 'Spot' not in color_mode
        mode_color = '#c0392b' if is_warning else '#1a6b3a'
        mode_icon = '⚠️' if is_warning else '✅'
        badge = f'<div style="display:inline-block;padding:4px 12px;border-radius:12px;background:{mode_color};color:#fff;font-size:0.85rem;font-weight:bold;margin-bottom:8px;">{mode_icon} Document Color Mode: {color_mode}</div>'
        st.markdown(badge, unsafe_allow_html=True)
        if is_warning:
            st.warning("⚠️ RGB color mode detected — colors may shift significantly in print. CMYK or Spot Color recommended.")

    # Spot colors (Pantone)
    if color_data.get('spot_colors'):
        st.markdown("**🎯 Spot Colors (Pantone/Named):**")
        for sc in color_data['spot_colors']:
            label = sc['label']
            swatch = '<span style="display:inline-block;width:16px;height:16px;background:#888;border:1px solid #666;border-radius:3px;vertical-align:middle;margin-right:6px;"></span>'
            st.markdown(f"{swatch}<code>{label}</code>", unsafe_allow_html=True)

    # Fill colors
    if color_data.get('fills'):
        st.markdown("**🩣 Fill Colors:**")
        for fill in color_data['fills']:
            hex_val = fill.get('hex', '#cccccc')
            opacity = fill.get('opacity', 100)
            opacity_str = f" @ {opacity}% opacity" if opacity < 100 else ""
            swatch = f'<span style="display:inline-block;width:16px;height:16px;background:{hex_val};border:1px solid #666;border-radius:3px;vertical-align:middle;margin-right:6px;"></span>'
            st.markdown(
                f'{swatch}<code>{fill["label"]}</code>{opacity_str} <span style="color:#888;font-size:0.85rem;">({fill.get("space","")})</span>',
                unsafe_allow_html=True
            )

    # Stroke colors
    if color_data.get('strokes'):
        st.markdown("**✏️ Stroke Colors:**")
        for stroke in color_data['strokes']:
            hex_val = stroke.get('hex', '#cccccc')
            width = stroke.get('width', 1)
            hairline = " ⚠️ hairline" if width < 0.5 else ""
            swatch = f'<span style="display:inline-block;width:16px;height:16px;background:{hex_val};border:1px solid #666;border-radius:3px;vertical-align:middle;margin-right:6px;"></span>'
            st.markdown(
                f'{swatch}<code>{stroke["label"]}</code> — {width}pt{hairline}',
                unsafe_allow_html=True
            )

    # Gradients
    if color_data.get('gradients'):
        st.markdown("**🌈 Gradients:**")
        st.markdown(f"• {len(color_data['gradients'])} gradient(s) detected")

    # Warnings
    if color_data.get('warnings'):
        st.markdown("**⚠️ Production Warnings:**")
        for w in color_data['warnings']:
            st.warning(w)


# ============================================================================
# SIDEBAR - ASK ARTBOT
# ============================================================================

with st.sidebar:
    st.markdown("### 🤖 Ask ArtBot")
    st.caption("Your AI production assistant - 20+ years of industry knowledge")
    st.markdown("""
<div style="background:#1a2535;border-radius:8px;padding:12px 14px;margin-bottom:10px;border-left:3px solid #667eea;">
  <div style="font-size:1.3rem;font-weight:bold;color:#fff;margin-bottom:6px;">🤖 Got a file issue? Ask me.</div>
  <div style="font-size:0.95rem;color:#a0b8d0;margin-bottom:8px;">📁 File fixes &nbsp;·&nbsp; 🎨 Color questions &nbsp;·&nbsp; 🧵 Decoration methods &nbsp;·&nbsp; ✅ Best practices</div>
  <div style="font-size:0.9rem;color:#b0c4de;">Tell me what's going on and I'll tell you exactly how to tackle it and what to say to your customer.</div>
</div>
""", unsafe_allow_html=True)

    if "artbot_history" not in st.session_state:
        st.session_state.artbot_history = []
    if "artbot_input_value" not in st.session_state:
        st.session_state.artbot_input_value = ""
    if "artbot_input_key" not in st.session_state:
        st.session_state.artbot_input_key = 0
    if "artbot_pending" not in st.session_state:
        st.session_state.artbot_pending = None

    # Handle pending question (from example buttons or send)
    def _run_artbot(question):
        st.session_state.artbot_history.append({"role": "user", "content": question})
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
            full_response = ""
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=ARTBOT_SYSTEM_PROMPT,
                messages=st.session_state.artbot_history.copy()
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
            st.session_state.artbot_history.append({"role": "assistant", "content": full_response})
        except Exception as e:
            st.session_state.artbot_history.append({"role": "assistant", "content": f"⚠️ Error: {str(e)}"})

    if st.session_state.artbot_pending:
        q = st.session_state.artbot_pending
        st.session_state.artbot_pending = None
        st.session_state.artbot_input_value = ""
        _run_artbot(q)
        st.rerun()

    # Scrollable chat history box
    chat_html = ""
    if not st.session_state.artbot_history:
        chat_html = '<div style="color:#666;font-size:0.85rem;text-align:center;padding-top:30px;">Ask me anything about files,<br>colors, or decoration methods!</div>'
    for msg in st.session_state.artbot_history:
        if msg["role"] == "user":
            chat_html += f'''<div style="margin:4px 0;padding:6px 10px;background:#2b2d42;border-radius:10px 10px 3px 10px;color:#fff;font-size:0.95rem;text-align:right;">{msg["content"]}</div>'''
        else:
            chat_html += f'''<div style="margin:4px 0;padding:6px 10px;background:#1e3a5f;border-radius:10px 10px 10px 3px;color:#e0e0e0;font-size:0.95rem;">🤖 {msg["content"]}</div>'''
    st.markdown(
        f'''<div style="height:500px;overflow-y:auto;padding:6px;border:1px solid #333;border-radius:8px;background:#111;margin-bottom:8px;">{chat_html}</div>''',
        unsafe_allow_html=True
    )

    # Example question chips — only show when no history
    if not st.session_state.artbot_history:
        st.caption("💡 Try one of these:")
        examples = [
            "What file format for screen printing?",
            "How many colors for embroidery?",
            "What DPI for a 2 inch logo?",
            "Difference between vector and raster?",
            "Can I use gradients on shirts?",
            "Why did my file get rejected?",
            "What's a stitch count?",
            "How do I handle a customer pushing back on art fees?",
        ]
        for ex in examples:
            if st.button(ex, use_container_width=True, key=f"ex_{ex}"):
                st.session_state.artbot_pending = ex
                st.rerun()

    # Input + send button — form allows Enter key to submit
    with st.form(key=f"artbot_form_{st.session_state.artbot_input_key}", clear_on_submit=True):
        q_col, btn_col = st.columns([5, 1])
        with q_col:
            question_input = st.text_input("q", placeholder="Ask anything...",
                label_visibility="collapsed")
        with btn_col:
            send = st.form_submit_button("➤", use_container_width=True, type="primary")

    if st.session_state.artbot_history:
        if st.button("🔄 Clear conversation", use_container_width=True):
            st.session_state.artbot_history = []
            st.session_state.artbot_input_key += 1
            st.rerun()

    if send and question_input.strip():
        st.session_state.artbot_pending = question_input.strip()
        st.session_state.artbot_input_key += 1
        st.rerun()

# ============================================================================
# FILE UPLOAD SECTION
# ============================================================================

st.markdown("""
<div style="padding:2rem 0 1.5rem 0;">
    <div style="font-size:2.8rem;font-weight:800;background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1.1;margin-bottom:0.5rem;">
        🎨 ArtCheck
    </div>
    <div style="font-size:1.25rem;color:#ccc;font-weight:400;margin-bottom:1rem;">
        Instant art file screening for promotional products professionals.
    </div>
    <div style="font-size:0.95rem;color:#888;max-width:720px;line-height:1.7;">
        Built for sales reps and customer service teams who need quick answers on art files — 
        without waiting on the art department. Upload any vector, embroidery, or image file 
        to get an instant preview, color analysis, and production suitability check. 
        Ask ArtBot in the sidebar for expert guidance on file requirements, decoration methods, 
        and what to tell your customer.
    </div>
</div>
<hr style="border:none;border-top:1px solid #333;margin-bottom:1.5rem;">
""", unsafe_allow_html=True)

st.markdown("## 📁 Upload Your File")

vector_formats = ".ai, .eps, .pdf, .svg, .cdr, .xcf"
embroidery_formats = ".dst, .pes, .exp, .jef, .vp3, .xxx, .u01"

raster_formats = ".png, .jpg, .gif, .tiff, .bmp, .webp"
st.info(f"**Supported:** Vector files ({vector_formats}) | Embroidery files ({embroidery_formats}) | Raster images ({raster_formats})")

uploaded_file = st.file_uploader(
    "🎨 Drag and drop your file here or click to browse",
    type=['ai', 'eps', 'pdf', 'svg', 'cdr', 'xcf', 'indd', 'dst', 'pes', 'exp', 'jef', 'vp3', 'xxx', 'u01',
          'png', 'jpg', 'jpeg', 'gif', 'tiff', 'tif', 'bmp', 'webp'],
    help="Supports vector, embroidery, and raster image files up to 200MB"
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

    # Handle raster images separately
    raster_analyzer = RasterAnalyzer()
    if raster_analyzer.is_raster(uploaded_file.name):
        st.info("📷 Raster image detected — analyzing for production suitability...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        # Show the image as preview
        st.image(uploaded_file, caption="Your Image", use_container_width=True)

        # Run analysis
        analysis = raster_analyzer.analyze(tmp_path)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

        render_raster_results(analysis, uploaded_file.name)
        st.stop()

    # Background options — use session state so selection survives the Generate button click
    if 'bg_type' not in st.session_state:
        st.session_state.bg_type = 'auto'

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("🔄 Auto", use_container_width=True):
            st.session_state.bg_type = 'auto'
    with col2:
        if st.button("☀️ Light", use_container_width=True):
            st.session_state.bg_type = 'light'
    with col3:
        if st.button("🌙 Dark", use_container_width=True):
            st.session_state.bg_type = 'dark'
    with col4:
        if st.button("⬜ Transparent", use_container_width=True):
            st.session_state.bg_type = 'transparent'

    bg_type = st.session_state.bg_type
    st.caption(f"Background: **{bg_type.title()}**")

    # Generate Preview
    if st.button("🚀 Generate Preview", use_container_width=True, type="primary"):
        with st.spinner("Generating preview..."):
            # Save uploaded file to temp location
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name
        
            generator = PreviewGenerator()
            result = generator.generate_preview(tmp_path, bg_type)

            # Extract colors from vector source before cleanup
            color_data = None
            file_ext = Path(uploaded_file.name).suffix.lower()
            if file_ext in [".pdf", ".ai", ".eps", ".svg"]:
                extractor = ColorExtractor()
                color_data = extractor.extract(tmp_path)

            # Cleanup temp input
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        
            if result:
                st.markdown('<div class="success-box">✅ Preview generated successfully!</div>', 
                          unsafe_allow_html=True)
            
                # Display preview and info
                col1, col2 = st.columns([2, 1])
            
                with col1:
                    st.image(result['image'], caption="Your Preview", use_container_width=True)
            
                with col2:
                    st.markdown("### Preview Info")
                    w_in = round(result["width"] / 300, 2)
                    h_in = round(result["height"] / 300, 2)
                    st.metric("Dimensions (px)", f"{result["width"]} × {result["height"]}")
                    st.metric("Size @ 300dpi", f"{w_in}in × {h_in}in")
                    st.metric("File Size", f"{result['size_kb']} KB")
                    st.metric("File Type", result['file_type'].title())
                
                    if 'embroidery_info' in result:
                        emb = result['embroidery_info']
                        st.markdown("### 🧵 Embroidery Info")
                        st.metric("Stitch Count", f"{emb['stitch_count']:,}")
                        st.metric("Thread Changes", emb['thread_changes'])
                        st.metric("Size", f"{emb['width_mm']}mm × {emb['height_mm']}mm")
                
                    st.markdown("---")
                
                    # Download preview
                    with open(result['image'], 'rb') as f:
                        st.download_button(
                            label="⬇️ Download Preview (PNG)",
                            data=f,
                            file_name=f"{Path(uploaded_file.name).stem}_preview.png",
                            mime="image/png",
                            use_container_width=True
                        )

                # Color analysis below the two-column preview
                if color_data:
                    render_color_results(color_data, Path(uploaded_file.name).suffix.lower())

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Built with ❤️ for promotional products professionals</p>
    <p>🤖 AI-powered answers • 📁 Instant previews • ⏱️ Save 15+ hours/week</p>
</div>
""", unsafe_allow_html=True)
