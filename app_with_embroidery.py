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

    def _convert_with_fitz(self, input_file, output_file):
        """Convert PDF or SVG to PNG using PyMuPDF (fitz) - handles AI-native PDFs"""
        if not self.has_fitz:
            return False
        try:
            doc = self.fitz.open(input_file)
            page = doc[0]
            # Render at 2x scale for quality
            mat = self.fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat, alpha=False)
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
        elif ext in ['.pdf', '.ai', '.eps']:
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

        if ext == '.pdf' or ext == '.ai' or ext == '.eps':
            # For PDFs (including AI-native): use fitz first, pdf2image as fallback
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


def save_as_pdf(image_path, pdf_path):
    """Save preview as PDF"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.utils import ImageReader
        
        img = Image.open(image_path)
        c = canvas.Canvas(pdf_path, pagesize=letter)
        page_width, page_height = letter
        
        # Calculate scaling
        img_aspect = img.width / img.height
        page_aspect = page_width / page_height
        
        if img_aspect > page_aspect:
            scale = page_width / img.width * 0.9
        else:
            scale = page_height / img.height * 0.9
        
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


# ============================================================================
# MAIN APP
# ============================================================================

st.markdown('<h1 class="main-header">🎨 ArtCheck</h1>', unsafe_allow_html=True)
st.markdown('<p class="tagline">Vector & Embroidery File Preview Generator + AI Production Assistant</p>', unsafe_allow_html=True)

# ============================================================================
# SIDEBAR - ASK ARTBOT
# ============================================================================

with st.sidebar:
    st.markdown("### 🤖 Ask ArtBot")
    st.caption("Your AI production assistant - 20+ years of industry knowledge")

    if "artbot_history" not in st.session_state:
        st.session_state.artbot_history = []
    if "artbot_input_value" not in st.session_state:
        st.session_state.artbot_input_value = ""

    # Scrollable chat history box
    chat_html = ""
    if not st.session_state.artbot_history:
        chat_html = '<div style="color:#666;font-size:0.85rem;text-align:center;padding-top:30px;">Ask me anything about files,<br>colors, or decoration methods!</div>'
    for msg in st.session_state.artbot_history:
        if msg["role"] == "user":
            chat_html += f'''<div style="margin:4px 0;padding:6px 10px;background:#2b2d42;border-radius:10px 10px 3px 10px;color:#fff;font-size:0.85rem;text-align:right;">{msg["content"]}</div>'''
        else:
            chat_html += f'''<div style="margin:4px 0;padding:6px 10px;background:#1e3a5f;border-radius:10px 10px 10px 3px;color:#e0e0e0;font-size:0.85rem;">🤖 {msg["content"]}</div>'''
    st.markdown(
        f'''<div style="height:380px;overflow-y:auto;padding:6px;border:1px solid #333;border-radius:8px;background:#111;margin-bottom:8px;">{chat_html}</div>''',
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
        ]
        for ex in examples:
            if st.button(ex, use_container_width=True, key=f"ex_{ex}"):
                st.session_state.artbot_history.append({"role": "user", "content": ex})
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
                st.rerun()

    # Input + send button
    q_col, btn_col = st.columns([5, 1])
    with q_col:
        question_input = st.text_input("q", value=st.session_state.artbot_input_value,
            placeholder="Ask anything...", key="artbot_input", label_visibility="collapsed")
    with btn_col:
        send = st.button("➤", use_container_width=True, type="primary")

    if st.session_state.artbot_history:
        if st.button("🔄 Clear conversation", use_container_width=True):
            st.session_state.artbot_history = []
            st.session_state.artbot_input_value = ""
            st.rerun()

    question = question_input.strip() if send and question_input.strip() else None

    if question:
        st.session_state.artbot_input_value = ""  # Clear input on next rerun
        st.session_state.artbot_history.append({"role": "user", "content": question})
        with st.spinner("🤖 thinking..."):
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
                st.rerun()
            except Exception as e:
                err = f"⚠️ Error: {str(e)}"
                st.session_state.artbot_history.append({"role": "assistant", "content": err})
                st.rerun()

# ============================================================================
# FILE UPLOAD SECTION
# ============================================================================




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

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Built with ❤️ for promotional products professionals</p>
    <p>🤖 AI-powered answers • 📁 Instant previews • ⏱️ Save 15+ hours/week</p>
</div>
""", unsafe_allow_html=True)
