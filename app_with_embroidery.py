"""
ArtCheck - Enhanced with Embroidery File Support
Handles vector files AND embroidery files (.dst, .pes, .exp, etc.)
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
                    # Could add color change logic here
                
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
    """Handles conversion of vector files to PNG previews"""
    
    SUPPORTED_FORMATS = ['.ai', '.eps', '.pdf', '.svg', '.cdr', '.xcf']
    DEFAULT_DPI = 300
    PREVIEW_MAX_WIDTH = 1200
    PREVIEW_MAX_HEIGHT = 1200
    
    def __init__(self):
        self.has_inkscape = shutil.which('inkscape') is not None
        self.has_imagemagick = shutil.which('convert') is not None
        self.embroidery = EmbroideryConverter()
    
    def is_supported(self, filename):
        """Check if file format is supported"""
        ext = Path(filename).suffix.lower()
        return ext in self.SUPPORTED_FORMATS or self.embroidery.is_embroidery_file(filename)
    
    def _convert_with_inkscape(self, input_file, output_file, dpi):
        """Convert using Inkscape"""
        try:
            input_path = Path(input_file)
            ext = input_path.suffix.lower()
            
            cmd = [
                'inkscape',
                str(input_file),
                '--export-type=png',
                f'--export-dpi={dpi}',
                f'--export-filename={output_file}'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                # Inkscape failed, fallback available
                return False
                
            if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                # Empty output, fallback available
                return False
                
            st.success(f"✓ Converted {ext} with Inkscape")
            return True
        except Exception as e:
            # Inkscape error, fallback available
            return False
    
    def _convert_with_imagemagick(self, input_file, output_file, dpi):
        """Convert using ImageMagick"""
        try:
            input_path = Path(input_file)
            ext = input_path.suffix.lower()
            
            # XCF (GIMP files) - ImageMagick can handle these
            if ext == '.xcf':
                cmd = ['convert', '-flatten', '-density', str(dpi), 
                       str(input_file), str(output_file)]
            # CDR (CorelDRAW) - ImageMagick needs special handling
            elif ext == '.cdr':
                cmd = ['convert', '-density', str(dpi), 
                       str(input_file), '-flatten', str(output_file)]
            elif ext == '.svg':
                cmd = ['convert', '-background', 'none', '-density', str(dpi), 
                       str(input_file), str(output_file)]
            elif ext in ['.eps', '.ai']:
                # EPS/AI need Ghostscript - try multiple approaches
                # First try: Simple conversion
                cmd = [
                    'convert',
                    '-density', str(dpi),
                    str(input_file),
                    '-flatten',
                    str(output_file)
                ]
            else:
                # PDF
                cmd = ['convert', '-density', str(dpi), '-background', 'none',
                       f'{input_file}[0]', '-flatten', str(output_file)]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                # Try alternate EPS method
                if ext in ['.eps', '.ai']:
                    st.info("Trying alternate conversion method for EPS...")
                    cmd2 = [
                        'convert',
                        '-density', str(dpi),
                        '-background', 'white',
                        '-flatten',
                        str(input_file),
                        str(output_file)
                    ]
                    result = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
                    if result.returncode != 0:
                        st.error(f"ImageMagick failed: {result.stderr[:200] if result.stderr else 'Unknown error'}")
                        return False
                else:
                    st.error(f"ImageMagick failed: {result.stderr[:200] if result.stderr else 'Unknown error'}")
                    return False
                
            success = os.path.exists(output_file) and os.path.getsize(output_file) > 0
            if success:
                st.success(f"✓ Converted {ext} with ImageMagick")
            else:
                st.error(f"ImageMagick created empty file for {ext}")
            return success
        except Exception as e:
            st.error(f"ImageMagick error: {str(e)[:100]}")
            return False
    
    def rgb_to_cmyk(self, r, g, b):
        """Convert RGB to CMYK for print"""
        if (r, g, b) == (0, 0, 0):
            return {'c': 0, 'm': 0, 'y': 0, 'k': 100}
        
        # RGB to CMY
        c = 1 - r / 255.0
        m = 1 - g / 255.0
        y = 1 - b / 255.0
        
        # Extract K
        k = min(c, m, y)
        if k == 1:
            return {'c': 0, 'm': 0, 'y': 0, 'k': 100}
        
        # Calculate CMY
        c = round((c - k) / (1 - k) * 100)
        m = round((m - k) / (1 - k) * 100)
        y = round((y - k) / (1 - k) * 100)
        k = round(k * 100)
        
        return {'c': c, 'm': m, 'y': y, 'k': k}
    
    def get_color_name(self, r, g, b):
        """Get a basic color name"""
        # Simple color naming
        if r > 200 and g > 200 and b > 200:
            return "White"
        if r < 50 and g < 50 and b < 50:
            return "Black"
        if r > g and r > b:
            if g > 100:
                return "Orange/Gold"
            return "Red"
        if g > r and g > b:
            return "Green"
        if b > r and b > g:
            return "Blue"
        if r > 150 and g > 150:
            return "Yellow"
        if r > 100 and b > 100:
            return "Purple"
        return "Gray"
    
    def _get_used_spot_colors_ghostscript(self, file_path):
        """Use Ghostscript to detect spot colors ACTUALLY USED in the file"""
        try:
            import re
            
            # Use Ghostscript's inkcov device to get ink coverage info
            # This shows which spot colors are actually used, not just defined
            result = subprocess.run(
                ['gs', '-o', '-', '-sDEVICE=inkcov', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                output = result.stdout
                # Look for PANTONE color names in the output
                # inkcov will list spot colors that are actually used
                pantone_pattern = r'PANTONE\s+(\d+(?:-\d+)?)\s*([A-Z]{1,3})'
                matches = re.finditer(pantone_pattern, output, re.IGNORECASE)
                
                used_pantones = set()
                for match in matches:
                    number = match.group(1)
                    variant = match.group(2).upper()
                    pantone_name = f"PANTONE {number} {variant}"
                    used_pantones.add(pantone_name)
                
                return list(used_pantones)
        except Exception as e:
            # Silently fall back to text parsing method
            return []
        
        return []
    
    def extract_vector_colors(self, file_path):
        """Extract actual colors from vector paths in AI/EPS/PDF/CDR files"""
        try:
            ext = Path(file_path).suffix.lower()
            # CDR, XCF are harder to parse - skip color extraction for now
            # (preview will still work, just won't extract Pantone colors)
            if ext not in ['.ai', '.eps', '.pdf', '.svg']:
                return None
            
            colors_found = {
                'pantone': [],
                'cmyk': [],
                'rgb': [],
                'grayscale': [],
                'spot_other': []
            }
            
            # Read file
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                    text = content.decode('latin-1', errors='ignore')
            except:
                return None
            
            import re
            
            # === PANTONE COLORS ===
            # First, try Ghostscript for ACTUALLY USED spot colors
            gs_pantones = self._get_used_spot_colors_ghostscript(file_path)
            
            # If Ghostscript found Pantone colors, use those (most accurate)
            if gs_pantones:
                colors_found['pantone'] = sorted(gs_pantones)
            else:
                # Fallback: Parse file text for Pantone references
                # Match all Pantone variants: C, U, PC, PU, CVC, TPX, TCX, etc.
                pantone_patterns = [
                    r'PANTONE\s+(\d+(?:-\d+)?)\s*([A-Z]{1,3})',  # PANTONE 293 U, PANTONE 293 CVC, etc.
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
                
                colors_found['pantone'] = sorted(list(pantone_set))
            
            # === CMYK PROCESS COLORS ===
            # Look for CMYK fill operations in PostScript/PDF
            # Pattern: "C M Y K setcmykcolor" or "C M Y K k" (fill)
            cmyk_patterns = [
                r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(?:setcmykcolor|k)',
                r'/DeviceCMYK\s+.*?\[([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\]',
            ]
            
            cmyk_set = set()
            for pattern in cmyk_patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    c = float(match.group(1))
                    m = float(match.group(2))
                    y = float(match.group(3))
                    k = float(match.group(4))
                    
                    # Convert 0-1 range to 0-100%
                    if c <= 1.0:
                        c = int(c * 100)
                        m = int(m * 100)
                        y = int(y * 100)
                        k = int(k * 100)
                    else:
                        c = int(c)
                        m = int(m)
                        y = int(y)
                        k = int(k)
                    
                    # Include ALL colors including white (0,0,0,0)
                    cmyk_tuple = (c, m, y, k)
                    cmyk_set.add(cmyk_tuple)
            
            # Convert to list, sorted by usage (K first, then C, M, Y)
            colors_found['cmyk'] = sorted(list(cmyk_set), key=lambda x: (x[3], x[0], x[1], x[2]))[:15]
            
            # === GRAYSCALE COLORS ===
            # Look for grayscale operations: "G setgray" or "G g"
            gray_patterns = [
                r'([\d.]+)\s+(?:setgray|g)\s',
                r'/DeviceGray\s+.*?\[([\d.]+)\]',
            ]
            
            gray_set = set()
            
            # Check for explicit "White" color name in swatches
            if re.search(r'/White[\s\)]|"White"|\'White\'|\(White\)', text, re.IGNORECASE):
                gray_set.add(100)  # Add white if we find the name
                st.success("✓ Found 'White' color swatch in file")
            
            for pattern in gray_patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    gray_value = float(match.group(1))
                    
                    # Convert to 0-100% (0 = black, 100 = white)
                    if gray_value <= 1.0:
                        gray_percent = int(gray_value * 100)
                    else:
                        gray_percent = int(gray_value)
                    
                    gray_set.add(gray_percent)
            
            colors_found['grayscale'] = sorted(list(gray_set), reverse=True)[:10]  # White first
            
            # === RGB COLORS ===
            # Look for RGB operations: "R G B setrgbcolor" or "R G B rg"
            rgb_patterns = [
                r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(?:setrgbcolor|rg|RG)\s',
                r'/DeviceRGB\s+.*?\[([\d.]+)\s+([\d.]+)\s+([\d.]+)\]',
            ]
            
            rgb_set = set()
            for pattern in rgb_patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    r = float(match.group(1))
                    g = float(match.group(2))
                    b = float(match.group(3))
                    
                    # Convert 0-1 range to 0-255
                    if r <= 1.0:
                        r = int(r * 255)
                        g = int(g * 255)
                        b = int(b * 255)
                    else:
                        r = int(r)
                        g = int(g)
                        b = int(b)
                    
                    rgb_tuple = (r, g, b)
                    rgb_set.add(rgb_tuple)
            
            colors_found['rgb'] = sorted(list(rgb_set))[:15]
            
            # === OTHER SPOT COLORS (non-Pantone) ===
            # Look for separation color spaces
            separation_pattern = r'/Separation\s*/\(([^)]+)\)'
            matches = re.finditer(separation_pattern, text)
            for match in matches:
                color_name = match.group(1).strip()
                # Skip if it's already captured as Pantone
                if 'PANTONE' not in color_name.upper():
                    colors_found['spot_other'].append(color_name)
            
            # Remove duplicates
            colors_found['spot_other'] = list(set(colors_found['spot_other']))[:5]
            
            # Return None if nothing found
            if not colors_found['pantone'] and not colors_found['cmyk'] and not colors_found['rgb'] and not colors_found['grayscale'] and not colors_found['spot_other']:
                return None
            
            return colors_found
            
        except Exception as e:
            st.warning(f"Vector color extraction error: {str(e)[:150]}")
            return None
    
    def extract_pantone_colors(self, file_path):
        """Try to extract Pantone spot colors from AI/EPS files"""
        try:
            ext = Path(file_path).suffix.lower()
            if ext not in ['.ai', '.eps']:
                return None
            
            pantone_colors = []
            
            # Read file as text to find Pantone definitions
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                    # Try to decode as latin-1 (handles binary better)
                    text = content.decode('latin-1', errors='ignore')
            except:
                return None
            
            # Common Pantone patterns in EPS/AI files
            patterns = [
                r'PANTONE\s+(\d+)\s*([CUP])',  # PANTONE 293 U
                r'/\(PANTONE\s+(\d+)\s*([CUP])\)',  # /(PANTONE 293 U)
                r'%%CMYKCustomColor:.*PANTONE\s+(\d+)\s*([CUP])',  # EPS comments
            ]
            
            import re
            found_pantones = set()
            
            for pattern in patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    number = match.group(1)
                    variant = match.group(2)
                    pantone_name = f"PANTONE {number} {variant}"
                    found_pantones.add(pantone_name)
            
            # Convert to list and sort
            if found_pantones:
                pantone_colors = sorted(list(found_pantones))
                st.success(f"✓ Found {len(pantone_colors)} Pantone color(s) in file")
                return pantone_colors
            
            return None
            
        except Exception as e:
            st.warning(f"Pantone extraction error: {str(e)[:100]}")
            return None
    
    def extract_colors(self, image_path, num_colors=6):
        """Extract dominant colors from image"""
        try:
            import colorgram
            
            colors = colorgram.extract(str(image_path), num_colors)
            
            results = []
            for color in colors:
                rgb = color.rgb
                cmyk = self.rgb_to_cmyk(rgb.r, rgb.g, rgb.b)
                color_name = self.get_color_name(rgb.r, rgb.g, rgb.b)
                results.append({
                    'rgb': (rgb.r, rgb.g, rgb.b),
                    'hex': '#{:02x}{:02x}{:02x}'.format(rgb.r, rgb.g, rgb.b),
                    'cmyk': cmyk,
                    'name': color_name,
                    'proportion': color.proportion
                })
            return results
        except ImportError:
            return None
        except Exception as e:
            st.warning(f"Color extraction error: {str(e)[:100]}")
            return None
    
    def calculate_physical_size(self, width_px, height_px, dpi=300):
        """Calculate physical size in inches"""
        width_inches = width_px / dpi
        height_inches = height_px / dpi
        return {
            'width_inches': round(width_inches, 2),
            'height_inches': round(height_inches, 2),
            'dpi': dpi
        }
    
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
        """Add watermark that scales with image size"""
        watermarked = img.copy()
        draw = ImageDraw.Draw(watermarked)
        
        # Much more aggressive scaling - 0.8-1.2% of image width
        font_size = max(8, min(int(img.width * 0.012), 16))  # Between 8-16px, smaller default
        
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except:
            font = ImageFont.load_default()
        
        # For very small images, use just initials
        if img.width < 200 or img.height < 200:
            text = "AC"  # Just initials for small images
        else:
            text = "ArtCheck"  # Shorter text
        
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Minimal padding for small images
        padding = max(2, int(font_size * 0.25))
        
        # Position in bottom right corner with minimal margin
        margin = max(3, int(img.width * 0.01))
        x = img.width - text_width - margin
        y = img.height - text_height - margin
        
        # Make background more transparent for subtlety
        draw.rectangle(
            [(x - padding, y - padding), 
             (x + text_width + padding, y + text_height + padding)],
            fill=(255, 255, 255, 140)
        )
        draw.text((x, y), text, fill=(120, 120, 120), font=font)
        
        return watermarked
    
    def generate_preview(self, input_file, bg_type='auto', dpi=300):
        """Generate preview from input file"""
        
        # Check if it's an embroidery file
        if self.embroidery.is_embroidery_file(input_file):
            return self._generate_embroidery_preview(input_file, bg_type)
        
        # Handle vector files
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_output = temp_file.name
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as pdf_temp:
            pdf_output = pdf_temp.name
        
        # Extract actual vector colors BEFORE conversion (from original file)
        vector_colors = self.extract_vector_colors(input_file)
        
        # Try conversion
        success = False
        if self.has_inkscape:
            success = self._convert_with_inkscape(input_file, temp_output, dpi)
            # Also create PDF version
            if success:
                self._convert_to_pdf(input_file, pdf_output, dpi)
        
        if not success and self.has_imagemagick:
            success = self._convert_with_imagemagick(input_file, temp_output, dpi)
            if success:
                self._convert_to_pdf(input_file, pdf_output, dpi)
        
        if not success or not os.path.exists(temp_output) or os.path.getsize(temp_output) == 0:
            if os.path.exists(temp_output):
                os.unlink(temp_output)
            if os.path.exists(pdf_output):
                os.unlink(pdf_output)
            return None
        
        # Process image
        try:
            img = Image.open(temp_output)
            
            # EXTRACT COLORS FIRST - from original converted file, before background!
            # We'll use this ONLY as fallback if vector colors weren't found
            sampled_colors = self.extract_colors(temp_output) if not vector_colors else None
            
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
            
            # Save final PNG
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as final_file:
                final_output = final_file.name
            
            img.save(final_output, 'PNG', optimize=True)
            
            if os.path.exists(temp_output):
                os.unlink(temp_output)
            
            result = {
                'image': img,
                'path': final_output,
                'width': img.width,
                'height': img.height,
                'brightness': round(brightness, 1),
                'size_kb': round(os.path.getsize(final_output) / 1024, 2),
                'file_type': 'vector',
                'physical_size': self.calculate_physical_size(img.width, img.height, dpi),
                'vector_colors': vector_colors,  # Actual colors from vector paths!
                'sampled_colors': sampled_colors  # Fallback only
            }
            
            # Add PDF if it was created
            if os.path.exists(pdf_output) and os.path.getsize(pdf_output) > 0:
                result['pdf_path'] = pdf_output
                result['pdf_size_kb'] = round(os.path.getsize(pdf_output) / 1024, 2)
            
            return result
            
        except Exception as e:
            st.error(f"Processing error: {e}")
            return None
    
    def _convert_to_pdf(self, input_file, output_file, dpi):
        """Convert file to PDF format - KEEPS VECTORS, doesn't rasterize"""
        try:
            input_path = Path(input_file)
            ext = input_path.suffix.lower()
            
            # If already PDF, just copy it
            if ext == '.pdf':
                import shutil
                shutil.copy(input_file, output_file)
                return True
            
            # For EPS/AI files, use Ghostscript (BEST for PostScript → PDF)
            if ext in ['.eps', '.ai']:
                cmd = [
                    'gs',
                    '-dNOPAUSE',
                    '-dBATCH',
                    '-sDEVICE=pdfwrite',
                    '-dEPSCrop',  # Crop to bounding box
                    f'-sOutputFile={output_file}',
                    str(input_file)
                ]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                        st.success("✅ Created vector PDF (scalable)")
                        return True
                except Exception as e:
                    st.warning(f"Ghostscript conversion failed: {e}")
            
            # Try Inkscape for SVG and CDR (BEST for SVG/CDR → PDF)
            if self.has_inkscape and ext in ['.svg', '.cdr']:
                cmd = [
                    'inkscape',
                    str(input_file),
                    '--export-type=pdf',
                    '--export-pdf-version=1.5',
                    '--export-text-to-path',
                    f'--export-filename={output_file}'
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0 and os.path.exists(output_file):
                    st.success("✅ Created vector PDF (scalable)")
                    return True
            
            # XCF files are raster, skip PDF conversion
            if ext == '.xcf':
                st.info("ℹ️ GIMP files are raster - no vector PDF available")
                return False
            
            # Remove old fallback code - Ghostscript handles EPS/AI now
            
            st.warning("⚠️ Could not create vector PDF")
            return False
            
        except Exception as e:
            st.error(f"PDF conversion error: {str(e)}")
            return False
    
    def _generate_embroidery_preview(self, input_file, bg_type):
        """Generate preview for embroidery file"""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_output = temp_file.name
        
        success, result = self.embroidery.convert_to_png(input_file, temp_output)
        
        if not success:
            st.error(f"Embroidery conversion failed: {result}")
            return None
        
        try:
            img = Image.open(temp_output)
            
            brightness = self.detect_brightness(img)
            img = self.add_background(img, bg_type)
            img = self.add_watermark(img)
            
            # Save final
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as final_file:
                final_output = final_file.name
            
            img.save(final_output, 'PNG', optimize=True)
            
            if os.path.exists(temp_output):
                os.unlink(temp_output)
            
            return {
                'image': img,
                'path': final_output,
                'width': img.width,
                'height': img.height,
                'brightness': round(brightness, 1),
                'size_kb': round(os.path.getsize(final_output) / 1024, 2),
                'file_type': 'embroidery',
                'embroidery_info': result
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
# Sidebar Help Section
with st.sidebar:
    st.markdown("## 🎨 ArtCheck")
    st.markdown("*Instant art file previews*")
    st.markdown("---")
    
    # Help & Education
    with st.expander("💬 Ask Art Department", expanded=False):
        st.markdown("### Common Questions")
        
        question = st.selectbox(
            "What do you need help with?",
            [
                "Select a question...",
                "Vector vs Raster - what's the difference?",
                "Why does it say RGB colors will shift?",
                "What are Pantone spot colors?",
                "What file format should I request?",
                "Why does my logo look blurry?",
            ],
            key="help_question"
        )
        
        if question == "Vector vs Raster - what's the difference?":
            st.info("""
            **Vector = Math-based (Scalable)**
            Like LEGO instructions - can build at any size, always perfect.
            Files: .AI, .EPS, .SVG, .PDF
            
            **Raster = Pixel-based (Fixed size)**
            Like a photo - made of tiny squares. Zoom too much = blurry.
            Files: .JPG, .PNG
            
            **For promo products? You want VECTOR!**
            Same logo works on a pen AND a banner.
            """)
            
        elif question == "Why does it say RGB colors will shift?":
            st.warning("""
            **RGB = Screen colors** (glowing light)
            **CMYK = Print colors** (ink on paper)
            
            Screens can show NEON bright colors that ink physically CAN'T make.
            
            When printed, bright RGB → muddy CMYK. It's physics, not a mistake!
            
            **Fix:** Use CMYK or Pantone colors.
            """)
            
        elif question == "What are Pantone spot colors?":
            st.success("""
            **Pantone = Paint swatches for printers**
            
            Each color has a number (PANTONE 293 U) and is mixed identically worldwide.
            
            **Why use them?**
            - Logo looks SAME on every product
            - No color shift
            - Vendors know exact ink
            
            Most promo products use Pantone!
            """)
            
        elif question == "What file format should I request?":
            st.success("""
            **Best to worst:**
            
            1. ✅ Vector PDF - Perfect!
            2. ✅ .AI or .EPS - Great!
            3. ✅ .SVG - Good!
            4. ⚠️ High-res PNG (300 DPI min)
            
            **AVOID:**
            - ❌ .JPG (compressed)
            - ❌ .INDD (needs InDesign)
            """)
            
        elif question == "Why does my logo look blurry?":
            st.warning("""
            **Two reasons:**
            
            1. **Raster file too small** - pixels stretched = blur
            2. **Preview quality low** - actual file is fine
            
            **Fix:** Get vector file OR higher DPI raster.
            """)
    
    st.markdown("---")
    st.caption("💡 Save your art team 15+ hours/week")

# Main App
st.markdown('<div class="main-header">🎨 ArtCheck - IT WORKS!</div>', unsafe_allow_html=True)
st.markdown('<div class="tagline">Vector & Embroidery File Preview Generator</div>', unsafe_allow_html=True)

# Supported formats
embroidery_formats = ', '.join(generator.embroidery.EMBROIDERY_FORMATS)
vector_formats = ', '.join(generator.SUPPORTED_FORMATS)

# Large, prominent file upload area with custom CSS
st.markdown("""
<style>
    /* Make file uploader HUGE and obvious */
    [data-testid="stFileUploader"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border: 4px dashed #ffffff;
        border-radius: 20px;
        padding: 60px 40px;
        text-align: center;
    }
    
    [data-testid="stFileUploader"] label {
        font-size: 28px !important;
        font-weight: bold !important;
        color: white !important;
    }
    
    [data-testid="stFileUploader"] section {
        border: none !important;
    }
    
    /* Make file name and buttons more visible */
    [data-testid="stFileUploader"] small {
        font-size: 18px !important;
        color: #f0f0f0 !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("### 📁 Upload Your File")
st.info(f"**Supported:** Vector files ({vector_formats}) | Embroidery files ({embroidery_formats})")

# File upload
uploaded_file = st.file_uploader(
    "🎨 Drag and drop your file here or click to browse",
    type=['ai', 'eps', 'pdf', 'svg', 'cdr', 'xcf', 'indd', 'dst', 'pes', 'exp', 'jef', 'vp3', 'xxx', 'u01'],
    help="Supports vector and embroidery files up to 200MB",
    label_visibility="visible"
)

if uploaded_file:
    # Check for InDesign files - provide helpful message
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
    
    bg_type = 'auto'
    if bg_light:
        bg_type = 'light'
    elif bg_dark:
        bg_type = 'dark'
    elif bg_transparent:
        bg_type = 'transparent'
    
    # Generate preview
    if st.button("🚀 Generate Preview", use_container_width=True, type="primary"):
        with st.spinner("Generating preview..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                tmp_file.write(uploaded_file.getbuffer())
                tmp_path = tmp_file.name
            
            result = generator.generate_preview(tmp_path, bg_type)
            
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            
            if result:
                st.markdown('<div class="success-box">✅ Preview generated successfully!</div>', 
                          unsafe_allow_html=True)
                
                # HUGE OBVIOUS FILE TYPE BANNER
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
                else:
                    st.markdown("""
                    <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); 
                                padding: 30px; 
                                border-radius: 15px; 
                                text-align: center;
                                margin: 20px 0;
                                border: 4px solid #f5576c;">
                        <h1 style="color: white; margin: 0; font-size: 48px;">⚠️ RASTER IMAGE</h1>
                        <p style="color: white; margin: 10px 0 0 0; font-size: 24px; font-weight: bold;">
                            NOT Scalable • May Pixelate • Request Vector!
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                
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
                    
                    # VECTOR COLORS (from actual file paths)
                    if 'vector_colors' in result and result['vector_colors']:
                        vc = result['vector_colors']
                        
                        st.markdown("### 🎨 Colors (from Vector Paths)")
                        
                        # PANTONE SPOT COLORS
                        if vc.get('pantone'):
                            st.success(f"✓ **Pantone Spot Colors:** {len(vc['pantone'])} found")
                            for pantone in vc['pantone']:
                                st.markdown(f"### **{pantone}**")
                            st.markdown("")
                        
                        # OTHER SPOT COLORS (non-Pantone)
                        if vc.get('spot_other'):
                            st.info(f"ℹ️ **Other Spot Colors:** {len(vc['spot_other'])} found")
                            for spot in vc['spot_other']:
                                st.markdown(f"**{spot}**")
                            st.markdown("")
                        
                        # ONLY show CMYK/Grayscale if NO Pantone colors found
                        # (When Pantone is present, CMYK/Grayscale are just separation noise)
                        if not vc.get('pantone'):
                            # CMYK PROCESS COLORS
                            if vc.get('cmyk'):
                                st.info(f"📊 **CMYK Process Colors:** {len(vc['cmyk'])} found")
                                for cmyk in vc['cmyk']:
                                    c, m, y, k = cmyk
                                    
                                    # Name the color
                                    if c == 0 and m == 0 and y == 0 and k == 0:
                                        color_name = "White"
                                    elif c == 0 and m == 0 and y == 0 and k == 100:
                                        color_name = "Black"
                                    elif c > 70 and m < 30 and y < 30:
                                        color_name = "Cyan"
                                    elif m > 70 and c < 30 and y < 30:
                                        color_name = "Magenta"
                                    elif y > 70 and c < 30 and m < 30:
                                        color_name = "Yellow"
                                    elif c > 50 and m > 50 and y < 30:
                                        color_name = "Blue"
                                    elif m > 50 and y > 50 and c < 30:
                                        color_name = "Red"
                                    elif c > 50 and y > 50 and m < 30:
                                        color_name = "Green"
                                    elif y > 80 and m > 30 and c < 20:
                                        color_name = "Orange/Gold"
                                    else:
                                        color_name = "Process Color"
                                    
                                    col_swatch, col_info = st.columns([1, 4])
                                    with col_swatch:
                                        # Approximate color swatch (convert CMYK to RGB for display)
                                        r = int(255 * (1 - c/100) * (1 - k/100))
                                        g = int(255 * (1 - m/100) * (1 - k/100))
                                        b = int(255 * (1 - y/100) * (1 - k/100))
                                        hex_color = f'#{r:02x}{g:02x}{b:02x}'
                                        color_box = f'<div style="width:50px;height:50px;background-color:{hex_color};border:2px solid #333;border-radius:6px;"></div>'
                                        st.markdown(color_box, unsafe_allow_html=True)
                                    with col_info:
                                        st.markdown(f"**{color_name}**")
                                        st.markdown(f"**CMYK: C:{c}% M:{m}% Y:{y}% K:{k}%**")
                                    st.markdown("")
                            
                            # GRAYSCALE COLORS
                            if vc.get('grayscale'):
                                st.info(f"⚪ **Grayscale Colors:** {len(vc['grayscale'])} found")
                                for gray in vc['grayscale']:
                                    # Name the color
                                    if gray >= 95:
                                        color_name = "White"
                                    elif gray <= 5:
                                        color_name = "Black"
                                    elif gray >= 70:
                                        color_name = "Light Gray"
                                    elif gray >= 40:
                                        color_name = "Medium Gray"
                                    else:
                                        color_name = "Dark Gray"
                                    
                                    col_swatch, col_info = st.columns([1, 4])
                                    with col_swatch:
                                        # Grayscale swatch
                                        gray_val = int(255 * gray / 100)
                                        hex_color = f'#{gray_val:02x}{gray_val:02x}{gray_val:02x}'
                                        color_box = f'<div style="width:50px;height:50px;background-color:{hex_color};border:2px solid #333;border-radius:6px;"></div>'
                                        st.markdown(color_box, unsafe_allow_html=True)
                                    with col_info:
                                        st.markdown(f"**{color_name}**")
                                        st.markdown(f"**Grayscale: {gray}% (K:{100-gray}%)**")
                                    st.markdown("")
                        
                        # RGB COLORS (with STRONG warning - will shift!)
                        # Always show RGB warnings regardless of other colors
                        if vc.get('rgb'):
                            st.error(f"🚨 **RGB Colors Detected:** {len(vc['rgb'])} found")
                            st.warning("**⚠️ CRITICAL: RGB colors will shift significantly when printed!**")
                            st.markdown("""
                            **Common issues:**
                            - Bright/neon RGB colors → Dull/muddy CMYK prints
                            - RGB blues → Purple-ish in CMYK
                            - RGB greens → Brown-ish in CMYK
                            - Vibrant screens → Disappointing prints
                            
                            **SOLUTION:** Convert file to CMYK or use Pantone spot colors for accurate results.
                            """)
                            
                            for rgb in vc['rgb']:
                                r, g, b = rgb
                                
                                # Get color name and CMYK conversion
                                color_name = self.get_color_name(r, g, b)
                                cmyk = self.rgb_to_cmyk(r, g, b)
                                
                                # Detect if color is likely to shift badly
                                is_bright = (r > 200 or g > 200 or b > 200) and not (r > 200 and g > 200 and b > 200)
                                shift_warning = " 🚨 HIGH SHIFT RISK" if is_bright else ""
                                
                                col_swatch, col_info = st.columns([1, 4])
                                with col_swatch:
                                    # RGB swatch
                                    hex_color = f'#{r:02x}{g:02x}{b:02x}'
                                    color_box = f'<div style="width:50px;height:50px;background-color:{hex_color};border:2px solid #333;border-radius:6px;"></div>'
                                    st.markdown(color_box, unsafe_allow_html=True)
                                with col_info:
                                    st.markdown(f"**{color_name}** ⚠️ RGB{shift_warning}")
                                    st.markdown(f"RGB({r}, {g}, {b}) → CMYK: C:{cmyk['c']}% M:{cmyk['m']}% Y:{cmyk['y']}% K:{cmyk['k']}%")
                                    if is_bright:
                                        st.caption("⚠️ This bright color will look significantly duller when printed!")
                                st.markdown("")
                            
                            st.error("⚠️ **Tell customer:** File must be converted to CMYK or use Pantone for accurate color matching!")
                        
                        st.caption("✓ Colors extracted from actual vector path fills")
                    
                    # FALLBACK: Sampled colors (only if no vector colors found)
                    elif 'sampled_colors' in result and result['sampled_colors']:
                        st.markdown("### 🎨 Color Analysis")
                        st.warning("⚠️ **Could not extract vector colors.** Showing sampled approximations (less accurate).")
                        
                        for i, color in enumerate(result['sampled_colors'][:6]):
                            col_swatch, col_info = st.columns([1, 4])
                            with col_swatch:
                                color_box = f'<div style="width:50px;height:50px;background-color:{color["hex"]};border:2px solid #333;border-radius:6px;"></div>'
                                st.markdown(color_box, unsafe_allow_html=True)
                            with col_info:
                                st.markdown(f"**{color['name']}** • {round(color['proportion']*100, 1)}%")
                                cmyk = color['cmyk']
                                st.caption(f"**CMYK: C:{cmyk['c']}% M:{cmyk['m']}% Y:{cmyk['y']}% K:{cmyk['k']}%**")
                            st.markdown("")
                    
                    # Show embroidery-specific info
                    if result.get('file_type') == 'embroidery' and 'embroidery_info' in result:
                        info = result['embroidery_info']
                        st.markdown("---")
                        st.markdown("### Embroidery Details")
                        st.metric("Stitch Count", f"{info['stitch_count']:,}")
                        st.metric("Thread Changes", info['thread_changes'])
                        st.metric("Design Size", f"{info['width_mm']} × {info['height_mm']} mm")
                    
                    st.markdown("---")
                    
                    # DYNAMIC DECORATION METHOD RECOMMENDATIONS
                    st.markdown("### 🎯 Recommended Decoration Methods")
                    st.caption("Based on your file analysis")
                    
                    # Analyze file properties
                    is_vector = result.get('file_type') == 'vector'
                    is_embroidery = result.get('file_type') == 'embroidery'
                    has_pantone = 'vector_colors' in result and result['vector_colors'] and result['vector_colors'].get('pantone')
                    has_rgb = 'vector_colors' in result and result['vector_colors'] and result['vector_colors'].get('rgb')
                    num_colors = 0
                    if 'vector_colors' in result and result['vector_colors']:
                        vc = result['vector_colors']
                        num_colors = len(vc.get('pantone', [])) + len(vc.get('cmyk', [])) + len(vc.get('rgb', []))
                    
                    # Generate smart recommendations
                    recommendations = []
                    
                    if is_vector and has_pantone and num_colors <= 3:
                        recommendations.append({
                            'method': '🎨 Screen Printing',
                            'rating': '⭐⭐⭐ EXCELLENT',
                            'why': f'Vector file with {len(result["vector_colors"]["pantone"])} Pantone spot color(s) - perfect for screen printing!',
                            'notes': 'Each Pantone color prints as exact match. Cost-effective for quantities over 50.'
                        })
                    
                    if is_vector and num_colors <= 6:
                        recommendations.append({
                            'method': '🧵 Embroidery',
                            'rating': '⭐⭐⭐ EXCELLENT',
                            'why': 'Clean vector shapes will digitize beautifully',
                            'notes': 'Keep text above 0.25" height. Simple shapes work best. Avoid tiny details under 2mm.'
                        })
                    
                    if is_vector:
                        recommendations.append({
                            'method': '✂️ Vinyl Cutting',
                            'rating': '⭐⭐⭐ EXCELLENT',
                            'why': 'Vector format - will cut precisely',
                            'notes': 'Best for single-color or simple multi-color designs. No gradients.'
                        })
                    
                    if is_vector or (result.get('physical_size') and '300 DPI' in str(result)):
                        recommendations.append({
                            'method': '👕 DTG (Direct to Garment)',
                            'rating': '⭐⭐ GOOD',
                            'why': 'High quality file suitable for full-color printing',
                            'notes': 'Works well for complex designs and photos. No minimums needed.'
                        })
                    
                    if has_rgb:
                        recommendations.append({
                            'method': '⚠️ RGB Color Warning',
                            'rating': '⚠️ NEEDS ATTENTION',
                            'why': 'File contains RGB colors that will shift when printed',
                            'notes': 'Convert to CMYK or use Pantone spot colors for accurate results.'
                        })
                    
                    if not is_vector:
                        recommendations.append({
                            'method': '⚠️ Raster File Limitation',
                            'rating': '⚠️ LIMITED OPTIONS',
                            'why': 'Raster/pixel-based file may not work for all methods',
                            'notes': 'DTG and sublimation will work if resolution is 300+ DPI. Screen printing and vinyl require vector files.'
                        })
                    
                    # Display recommendations
                    for rec in recommendations:
                        with st.container():
                            col_icon, col_content = st.columns([1, 5])
                            with col_icon:
                                rating_color = "green" if "EXCELLENT" in rec['rating'] else ("orange" if "GOOD" in rec['rating'] else "red")
                                st.markdown(f"<div style='font-size:24px; text-align:center;'>{rec['method'].split()[0]}</div>", unsafe_allow_html=True)
                            with col_content:
                                st.markdown(f"**{rec['method']}** • {rec['rating']}")
                                st.markdown(f"*{rec['why']}*")
                                st.caption(rec['notes'])
                            st.markdown("")
                    
                    # General guide link
                    with st.expander("📋 See all decoration methods comparison"):
                        st.markdown("""
                        ### Quick Reference Guide
                        
                        **Screen Printing:** 1-6 colors, vector, high qty (50+), exact Pantone matching
                        
                        **Embroidery:** Vector, simple shapes, 1-15 colors, premium look, no tiny text
                        
                        **DTG:** Full color, photos OK, any resolution 300+ DPI, low minimums (1+)
                        
                        **Vinyl:** Vector only, solid colors, no gradients, great for names/numbers
                        
                        **Laser Engraving:** Vector or high-contrast raster, single color, permanent
                        
                        **Sublimation:** Full color, photos, polyester only, 300+ DPI
                        
                        *See full FAQ below for detailed requirements and best practices*
                        """)
                    
                    st.markdown("---")
                    
                    # Download buttons
                    with open(result['path'], 'rb') as f:
                        st.download_button(
                            label="⬇️ Download PNG Preview",
                            data=f,
                            file_name=f"{Path(uploaded_file.name).stem}_preview.png",
                            mime="image/png",
                            use_container_width=True
                        )
                    
                    # PDF download if available
                    if 'pdf_path' in result and os.path.exists(result['pdf_path']):
                        st.markdown("---")
                        st.markdown("**📄 Vector PDF** *(Scalable - Send to Vendors)*")
                        col_pdf1, col_pdf2 = st.columns(2)
                        with col_pdf1:
                            st.metric("PDF Size", f"{result['pdf_size_kb']} KB")
                        with col_pdf2:
                            st.metric("Format", "Vector ✓")
                        with open(result['pdf_path'], 'rb') as f:
                            st.download_button(
                                label="⬇️ Download Vector PDF",
                                data=f,
                                file_name=f"{Path(uploaded_file.name).stem}.pdf",
                                mime="application/pdf",
                                use_container_width=True,
                                type="secondary"
                            )
                        st.caption("✓ Scalable vector format • Perfect for print shops, embroidery digitizers, and vendors")
                    
                    # Cleanup PNG preview (but keep PDF for downloads!)
                    if os.path.exists(result['path']):
                        os.unlink(result['path'])
            else:
                st.error("❌ Failed to generate preview. Please try a different file.")

# Features
st.markdown("---")
st.markdown("### ✨ Features")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown("**⚡ 3-Second Generation**")
    st.write("Lightning-fast previews")

with col2:
    st.markdown("**🎨 Color Extraction**")
    st.write("Auto-detect colors & codes")

with col3:
    st.markdown("**📏 Size Calculator**")
    st.write("Shows dimensions in inches")

with col4:
    st.markdown("**📄 PDF Conversion**")
    st.write("Vector PDF for vendors")

# HELP SECTION - ART FILE FAQ
st.markdown("---")
st.markdown("## 📚 Art File FAQ")
st.caption("Common questions about file formats, colors, and quality")

with st.expander("📐 **Vector vs Raster - What's the Difference?**", expanded=False):
    col_v, col_r = st.columns(2)
    
    with col_v:
        st.markdown("""
        ### ✅ VECTOR (Good!)
        **What it is:** Made of math (paths and points)
        
        **Why it's good:**
        - Scales to ANY size without losing quality
        - Perfect for logos, text, illustrations
        - Small file sizes
        - Easy for vendors to work with
        
        **File types:** AI, EPS, PDF, SVG, CDR
        
        **What to tell customer:**
        *"Perfect! This vector file will print beautifully at any size."*
        """)
        
        with st.expander("📖 Read more (technical details)"):
            st.markdown("""
            **How vectors work:**
            Vector graphics use mathematical equations to define shapes. When you have a circle, 
            it's stored as "center point + radius" rather than thousands of colored pixels. This 
            means the computer can recalculate the shape at any resolution.
            
            **Why this matters for print:**
            - A 1-inch logo and a 10-foot banner use the SAME file
            - No loss of quality when scaling
            - Printers can output at their maximum resolution
            - File sizes stay small (equations, not millions of pixels)
            
            **Technical advantages:**
            - Resolution-independent (infinite DPI)
            - Editable paths and anchor points
            - Pantone/spot color support
            - Transparency without artifacts
            - Perfect for screen printing, vinyl cutting, laser engraving
            
            **Industry standard:**
            Professional print shops and decoration vendors ALWAYS prefer vector files. 
            It's the difference between "professional quality" and "best we can do."
            """)
    
    with col_r:
        st.markdown("""
        ### ⚠️ RASTER (Problems!)
        **What it is:** Made of pixels (tiny colored squares)
        
        **Why it's risky:**
        - Gets blurry/pixelated when enlarged
        - Large file sizes
        - Hard to edit colors
        - Can't scale up without losing quality
        
        **File types:** JPG, PNG, GIF, TIFF, XCF
        
        **What to tell customer:**
        *"We need the vector version for best results. The current file might look blurry when printed."*
        """)
        
        with st.expander("📖 Read more (technical details)"):
            st.markdown("""
            **How raster images work:**
            Raster graphics are grids of colored pixels. A 100x100px image has 10,000 individual 
            colored squares. When you enlarge it, you're just making those squares bigger - 
            you can't add detail that wasn't there.
            
            **The resolution problem:**
            - 72 DPI = screen quality (looks good on monitors)
            - 150 DPI = bare minimum for print (will show pixelation)
            - 300 DPI = print standard (acceptable quality)
            - 600+ DPI = high quality print
            
            **Why file size explodes:**
            Doubling the print size = 4x the pixels = 4x the file size
            A 300 DPI image at 24" × 36" = 180+ megabytes!
            
            **Editing limitations:**
            - Can't cleanly change colors (edge artifacts)
            - Can't resize without quality loss
            - Backgrounds are "baked in"
            - Text becomes uneditable pixels
            
            **When raster is acceptable:**
            - Photographs (no vector equivalent exists)
            - Complex gradients/effects as placed images
            - Small decorations where scaling isn't needed
            - Digital-only applications (web, email)
            
            **The fix:**
            If you only have raster, either:
            1. Get the original vector from the designer
            2. Have it recreated/traced (costs money, won't be perfect)
            3. Use it only at its current size (risky)
            """)
    

with st.expander("🎨 **Color Issues Explained**", expanded=False):
    st.markdown("""
    ### 🚨 RGB Colors (Screen Colors)
    **The problem:** Computer screens use RGB (Red, Green, Blue) light. Printers can't print light!
    
    **What happens:** Bright, vibrant screen colors → Dull, muddy prints
    
    **Common examples:**
    - Neon colors look amazing on screen → Print like dirt
    - Bright blues → Turn purple-ish
    - Bright greens → Turn brown-ish
    
    **What to tell customer:**
    *"Your file uses RGB screen colors that will shift when printed. We recommend converting to CMYK or using Pantone spot colors for accurate color matching."*
    
    ---
    
    ### ✅ CMYK Colors (Print Colors)
    **What it is:** Cyan, Magenta, Yellow, Black - the four ink colors printers use
    
    **Why it's good:** What you see is (mostly) what you get
    
    **What to tell customer:**
    *"Perfect! Your file is already set up for printing."*
    
    ---
    
    ### 🎯 PANTONE Colors (Spot Colors)
    **What it is:** Pre-mixed ink colors with exact color codes (like paint swatches)
    
    **Why it's the BEST:**
    - Exact color matching every time
    - No color shift
    - Industry standard for logos
    
    **What to tell customer:**
    *"Great! Your Pantone colors will print exactly as expected."*
    """)
    
    with st.expander("📖 Read more (technical details)"):
        st.markdown("""
        **Understanding color spaces:**
        
        **RGB (Additive Color):**
        - How monitors work: Red + Green + Blue light
        - Gamut: ~16.7 million colors
        - Can create VERY bright colors (neons, electric blues)
        - Problem: Printers don't emit light!
        
        **CMYK (Subtractive Color):**
        - How printing works: Cyan, Magenta, Yellow, Black ink
        - Gamut: ~1 million colors (much smaller than RGB)
        - Light is absorbed/reflected, not emitted
        - Result: Duller than RGB, but printable
        
        **Why the shift happens:**
        RGB creates color with light (additive). CMYK creates color by absorbing light (subtractive).
        They're fundamentally different color models. RGB electric blue has no equivalent in CMYK ink.
        
        **Pantone Matching System (PMS):**
        - Pre-mixed inks (like paint swatches)
        - Each color has a specific formula
        - Industry-standard color communication
        - Gamut: Larger than CMYK, includes some colors CMYK can't make
        - Consistency: Same Pantone 293 U prints identically everywhere
        
        **When to use what:**
        - **Logos/branding:** ALWAYS Pantone (color consistency critical)
        - **Full color photos:** CMYK (can't print photos with spot colors)
        - **2-3 color designs:** Pantone (cheaper than CMYK for low color count)
        - **Complex artwork:** CMYK + Pantone spot for brand colors
        """)

with st.expander("🎯 **Will This File Work For... (Decoration Method Guide)**", expanded=False):
    st.markdown("""
    ### Screen Printing
    **Best with:** Vector files with Pantone spot colors
    
    **Requirements:**
    - ✅ Vector format (AI, EPS, PDF, SVG)
    - ✅ Spot colors separated (each color = one screen)
    - ✅ Clean edges (no gradients for simple designs)
    
    **Will work:** Vector files, high-res raster as halftones
    
    **Won't work well:** Low-res images, complex gradients (expensive)
    
    **What to tell customer:**
    *"Your vector file is perfect for screen printing! Each Pantone color will print as a separate screen."*
    
    ---
    
    ### Embroidery/Digitizing
    **Best with:** Simple vector files, limited colors
    
    **Requirements:**
    - ✅ Vector format (easier to digitize)
    - ✅ Clean, simple shapes (complex detail gets muddy)
    - ✅ Limited colors (thread color changes add cost)
    - ⚠️ No tiny text (minimum 0.25" for legibility)
    
    **Will work:** Clean logos, bold text, simple designs
    
    **Won't work well:** Photos, complex gradients, fine detail under 2mm
    
    **What to tell customer:**
    *"This design will embroider well. Simple shapes and bold lines translate perfectly to stitches."*
    
    ---
    
    ### DTG (Direct to Garment)
    **Best with:** Full color raster or vector
    
    **Requirements:**
    - ✅ High resolution (300 DPI minimum)
    - ✅ RGB or CMYK colors both work
    - ✅ Can handle photos and gradients
    
    **Will work:** Almost anything with good resolution
    
    **Won't work well:** Very low resolution, neon colors (will shift)
    
    **What to tell customer:**
    *"Your full-color design will print beautifully with DTG. It can handle all the detail and gradients."*
    
    ---
    
    ### Vinyl Cutting
    **Best with:** Simple vector, solid colors
    
    **Requirements:**
    - ✅ Vector format REQUIRED (AI, EPS, PDF, SVG)
    - ✅ Solid colors only (no gradients)
    - ✅ Single-layer or simple multi-layer
    - ⚠️ No fine detail (minimum 0.125" stroke width)
    
    **Will work:** Text, logos, simple graphics
    
    **Won't work:** Raster images, gradients, complex designs
    
    **What to tell customer:**
    *"Perfect for vinyl! Your vector file has clean paths that will cut precisely."*
    
    ---
    
    ### Laser Engraving
    **Best with:** High-contrast vector or raster
    
    **Requirements:**
    - ✅ Vector (best) or high-res raster
    - ✅ High contrast designs work best
    - ✅ Black & white or grayscale
    
    **Will work:** Logos, text, detailed line art
    
    **Won't work well:** Low contrast, full color (laser only does one color)
    
    **What to tell customer:**
    *"Your design will engrave beautifully. The clean lines will show great detail."*
    
    ---
    
    ### Sublimation
    **Best with:** Full color raster, photos
    
    **Requirements:**
    - ✅ High resolution (300 DPI minimum)
    - ✅ RGB colors (converts to CMYK for printing)
    - ✅ Can handle photos and complex designs
    - ⚠️ Only works on polyester/polymer-coated surfaces
    
    **Will work:** Photos, full color artwork, gradients
    
    **Won't work well:** Very low resolution, designs for dark fabrics
    
    **What to tell customer:**
    *"Your full-color design is perfect for sublimation. It will print with photographic quality."*
    """)
    
    with st.expander("📖 Read more (choosing the right method)"):
        st.markdown("""
        **Decision factors:**
        
        **Number of colors:**
        - 1-3 colors → Screen printing or vinyl (cheaper)
        - 4+ colors → DTG or sublimation (more economical)
        - Full color photo → DTG or sublimation only
        
        **Quantity:**
        - Under 12 pieces → DTG (no setup cost)
        - 12-50 pieces → DTG or screen print
        - 50+ pieces → Screen printing (setup cost amortized)
        - 200+ pieces → Screen printing wins on price
        
        **Substrate (what you're decorating):**
        - Cotton → Screen print or DTG
        - Polyester → Sublimation (if full color) or screen print
        - Vinyl/plastic → Screen print or pad print
        - Metal → Laser engraving or screen print
        - Glass/ceramic → Sublimation (if coated) or screen print
        
        **Detail level:**
        - Fine detail (under 2mm) → DTG, sublimation, laser
        - Medium detail → Screen print (with fine mesh)
        - Simple/bold → Any method works
        - Photographs → DTG or sublimation only
        
        **Durability needed:**
        - Maximum durability → Screen printing (thicker ink)
        - Good durability → DTG, embroidery
        - Moderate → Vinyl (can crack over time)
        - Permanent → Laser engraving (on hard goods)
        
        **Budget:**
        - Lowest cost (high qty) → Screen printing
        - Lowest setup → DTG
        - No minimums → DTG or sublimation
        - Premium look → Embroidery (perceived value)
        """)

with st.expander("⚠️ **Common File Problems & What to Say**", expanded=False):
    st.markdown("""
    ### 🔤 Missing Fonts / Text Not Outlined
    **The problem:** File uses fonts we don't have installed
    
    **What to tell customer:**
    *"Please outline your text (Type → Create Outlines in Illustrator) or send us the font files. This ensures your text looks exactly as you designed it."*
    """)
    
    with st.expander("📖 Read more (technical details)"):
        st.markdown("""
        **Why this happens:**
        Fonts are separate files installed on each computer. When you use "Arial Bold" in your design, 
        the file just says "use Arial Bold here" - it doesn't embed the actual font shapes. When we 
        open the file without that font installed, the computer substitutes a default font, changing 
        your design.
        
        **Solutions ranked by preference:**
        1. **Outline/Convert to paths** (BEST) - Text becomes vector shapes, no font needed
        2. **Embed fonts** - Some formats support this (PDF can embed)
        3. **Send font files** - Legal gray area, licensing issues
        4. **Use standard fonts** - Arial, Helvetica, Times always available
        
        **How to outline in different programs:**
        - **Illustrator:** Select text → Type menu → Create Outlines (Cmd/Ctrl+Shift+O)
        - **InDesign:** Select text → Type menu → Create Outlines
        - **CorelDRAW:** Select text → Object menu → Convert to Curves (Cmd/Ctrl+Q)
        
        **Trade-offs:**
        - ✅ Outlined text can't change accidentally
        - ✅ No font licensing issues
        - ❌ Can't edit text later (save a copy with live text!)
        - ❌ File size slightly increases
        """)
    
    st.markdown("""
    ---
    
    ### 📏 Low Resolution / Not Enough DPI
    **The problem:** Image is too small (not enough pixels)
    
    **What DPI means:** Dots Per Inch - we need 300 DPI minimum for print
    
    **What to tell customer:**
    *"This image is too low resolution and will look blurry when printed. We need a higher quality version - at least 300 DPI at the final print size."*
    """)
    
    with st.expander("📖 Read more (technical details)"):
        st.markdown("""
        **Understanding DPI/PPI:**
        - **72 DPI** = Screen resolution (monitors, web images)
        - **150 DPI** = Bare minimum for print (will show pixelation up close)
        - **300 DPI** = Print standard (good quality, industry norm)
        - **600+ DPI** = High-end print (magazines, fine art)
        
        **The math:**
        A 1000×1000 pixel image at different sizes:
        - At 72 DPI = 13.9" × 13.9" (looks great on screen!)
        - At 300 DPI = 3.3" × 3.3" (print quality)
        - At 600 DPI = 1.67" × 1.67" (high-end quality)
        
        **Why you can't just "increase DPI":**
        Changing the DPI setting doesn't add pixels - it just stretches the same pixels over 
        a different area. You can't create detail that wasn't captured originally.
        
        **Real solutions:**
        1. **Get original high-res file** from photographer/designer
        2. **Re-shoot/re-scan** at higher resolution
        3. **AI upscaling** (Topaz, Gigapixel) - adds "smart" pixels, not perfect
        4. **Use at smaller size** - if 1000px image, use it at ~3" not 10"
        
        **Prevention:**
        Always save/export images at final print size × 300 DPI. For an 8×10" print, 
        you need 2400×3000 pixels minimum.
        """)
    
    st.markdown("""
    ---
    
    ### 🎨 CMYK Out of Gamut
    **The problem:** Colors are too bright to print accurately with CMYK inks
    
    **What to tell customer:**
    *"Some colors in your file are outside the printable range. They'll shift to duller versions when printed. For exact color matching, we recommend using Pantone spot colors."*
    """)
    
    with st.expander("📖 Read more (technical details)"):
        st.markdown("""
        **What "gamut" means:**
        Gamut = the range of colors a device can produce. Different devices have different gamuts:
        - RGB monitors: ~16.7 million colors (very wide gamut)
        - CMYK printing: ~1 million colors (narrower gamut)
        - Pantone inks: Varies, but includes some colors CMYK can't make
        
        **The physics problem:**
        Monitors create color by emitting light (additive). Printers create color by absorbing light 
        with ink (subtractive). Some light-based colors physically cannot exist as ink colors.
        
        **Common out-of-gamut colors:**
        - Electric/neon blues (CMYK makes them purple-ish)
        - Bright lime greens (CMYK makes them olive/brown)
        - Hot pinks/magentas (CMYK makes them muddy)
        - Bright oranges (CMYK makes them dull)
        
        **How software handles it:**
        When converting RGB→CMYK, software "clips" out-of-gamut colors to the nearest CMYK 
        equivalent. "Perceptual" rendering tries to shift all colors proportionally. "Relative 
        colorimetric" clips only out-of-gamut colors.
        
        **Solutions:**
        1. **Use Pantone spot colors** for brand colors (bypasses CMYK entirely)
        2. **Design in CMYK** from the start (what you see is what you get)
        3. **Use soft-proofing** in Photoshop/Illustrator (View → Proof Colors)
        4. **Accept the shift** and adjust expectations
        """)
    
    st.markdown("""
    ---
    
    ### 🖼️ Linked Images Missing
    **The problem:** File references external images that aren't included
    
    **What to tell customer:**
    *"Your file is missing some linked images. Please use 'Package' or 'Collect for Output' to gather all files, or embed the images directly."*
    """)
    
    with st.expander("📖 Read more (technical details)"):
        st.markdown("""
        **How linking works:**
        Design programs can either:
        1. **Embed** images - Full image data stored in the design file (larger file)
        2. **Link** images - Just a reference/path to external file (smaller file)
        
        **Why linking exists:**
        - Keeps design files smaller
        - Updates automatically if source image changes
        - Multiple files can use same image
        
        **Why it causes problems:**
        - File says "use photo.jpg from /Users/Designer/Desktop/"
        - You send just the design file
        - We don't have photo.jpg in that exact folder
        - Result: Missing image box or low-res preview
        
        **How to fix in different programs:**
        
        **Illustrator:**
        - File → Package → Collects all files into one folder
        - Or: Select linked image → Embed Image (in Links panel)
        
        **InDesign:**
        - File → Package → Creates folder with all links
        - Or: Links panel → Select all → Embed Links
        
        **Best practice:**
        Always "Package" or "Collect for Output" before sending files. This creates a folder 
        with your design file + all linked images + fonts (if applicable).
        """)
    
    st.markdown("""
    ---
    
    ### ✂️ Bleeds Not Set Up
    **The problem:** Design doesn't extend past the cut line
    
    **What to tell customer:**
    *"Please extend your background colors/images 0.125 inches past the edge (bleed area) to avoid white edges after cutting."*
    """)
    
    with st.expander("📖 Read more (technical details)"):
        st.markdown("""
        **Why bleeds exist:**
        Printing and cutting are two separate operations:
        1. Print on oversized sheet
        2. Cut/trim to final size
        
        Problem: Cutting isn't perfectly precise (±0.5mm variation is normal). If your design 
        stops exactly at the cut line, any slight misalignment = white edge showing.
        
        **Standard bleed amounts:**
        - Business cards, postcards: 0.125" (1/8")
        - Posters, large format: 0.25" (1/4")
        - Books, magazines: 0.125" typically
        
        **What to extend:**
        - Background colors/images that go to edge
        - Borders or frames at the edge
        - Any element that "bleeds off" the page
        
        **What NOT to extend:**
        - Text (keep at least 0.125" INSIDE cut line - "safe area")
        - Logos or important elements near edge
        - QR codes or barcodes
        
        **How to set up bleeds:**
        
        **New document:**
        Most programs have "Bleed" settings when creating new document. Set to 0.125".
        
        **Existing document:**
        - Illustrator: File → Document Setup → Bleed settings
        - InDesign: File → Document Setup → Bleed and Slug
        - Photoshop: Image → Canvas Size → Add 0.25" total (0.125" each side)
        
        **Visual guide:**
        Final size = 8.5" × 11"
        With bleeds = 8.75" × 11.25" (add 0.125" on all sides)
        Extend background colors to 8.75" × 11.25"
        Keep text inside 8.25" × 10.75" (safe area)
        """)
    
    st.markdown("""
    ---
    
    ### 🎭 Spot Colors Not Separated
    **The problem:** Spot colors are mixed in with process colors
    
    **What to tell customer:**
    *"Your Pantone colors need to be set up as separate spot color channels for accurate printing."*
    """)
    
    with st.expander("📖 Read more (technical details)"):
        st.markdown("""
        **Understanding color channels:**
        
        **Process printing (CMYK):**
        Uses 4 color channels: Cyan, Magenta, Yellow, Black
        All colors made by mixing these 4 inks
        
        **Spot color printing:**
        Each spot color = its own ink = its own channel
        Pantone 293 Blue is pre-mixed blue ink, not CMYK mix
        
        **The separation problem:**
        If you use Pantone 293 but don't separate it properly:
        - File converts it to CMYK equivalent (C:100 M:91 Y:0 K:0)
        - Prints as CMYK mix (not actual Pantone ink)
        - Color shifts (not exact Pantone match)
        - Defeats the purpose of specifying Pantone!
        
        **How to set up spot colors correctly:**
        
        **Illustrator:**
        1. Window → Swatches → Open swatch library → Color Books → Pantone+ Solid Coated
        2. Click the Pantone color you want (creates spot color swatch)
        3. Make sure swatch shows dot icon (spot) not 4 squares (process)
        4. Use this swatch for your artwork
        
        **Color separation output:**
        Properly separated file with Pantone 293 + Black should have:
        - Pantone 293 U plate (all blue elements)
        - Black plate (all black elements)
        Total: 2 plates, 2 inks, 2 press runs
        
        **Why this matters for cost:**
        - 2 spot colors = 2 plates = affordable
        - 2 spot colors incorrectly converted to CMYK = 4 plates = more expensive
        - Plus you lose the exact color matching you paid for!
        
        **Checking your file:**
        - Illustrator: Window → Separations Preview
        - InDesign: Window → Output → Separations Preview
        - Shows each color plate separately - should see your Pantone as its own plate
        """)
    
    st.markdown("---")

with st.expander("💬 **Quick Copy-Paste Responses for Customers**", expanded=False):
    st.markdown("""
    ### When file is PERFECT:
    ```
    Great! Your file looks perfect. It's vector format with proper colors - 
    we're ready to move forward with production!
    ```
    
    ### When they send a raster file:
    ```
    Thanks for sending this! However, this is a raster/pixel-based file 
    which may not print clearly at larger sizes. Do you have the original 
    vector file (AI, EPS, or PDF)? That will give us the best quality results.
    ```
    
    ### When RGB colors detected:
    ```
    I've reviewed your file and noticed it uses RGB colors (screen colors) 
    rather than print colors. This means the colors will shift when printed - 
    bright colors typically print much duller. We can convert it for you, or 
    if exact color matching is important, we recommend using Pantone spot colors.
    ```
    
    ### When resolution is too low:
    ```
    The image resolution is a bit low for the size you want to print. At this 
    size, it may appear blurry or pixelated. Do you have a higher resolution 
    version? We need at least 300 DPI for sharp printing.
    ```
    
    ### When fonts need outlining:
    ```
    Quick heads up - your file has some fonts that need to be outlined to 
    ensure they print exactly as designed. In Illustrator, just select all 
    text and go to Type → Create Outlines. This converts text to shapes so 
    it can't accidentally change.
    ```
    """)

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Built with ❤️ for promotional products professionals</p>
    <p>Save your art department 15+ hours per week</p>
</div>
""", unsafe_allow_html=True)
