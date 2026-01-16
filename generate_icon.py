from PIL import Image, ImageDraw

def create_icon():
    # Size
    size = (256, 256)
    bg_color = (0, 0, 0, 0) # Transparent background
    circle_color = (0, 255, 255) # Aqua blue
    barcode_color = (0, 0, 0) # Black

    img = Image.new('RGBA', size, bg_color)
    draw = ImageDraw.Draw(img)

    # Draw Circle
    margin = 10
    draw.ellipse([margin, margin, size[0]-margin, size[1]-margin], fill=circle_color)

    # Draw Barcode (Simple lines)
    # Center area
    cx, cy = size[0] // 2, size[1] // 2
    w, h = 140, 100
    
    # Barcode bounds: x from cx-w/2 to cx+w/2
    start_x = cx - w // 2
    end_x = cx + w // 2
    top_y = cy - h // 2
    bottom_y = cy + h // 2

    import random
    random.seed(42) # Consistent result

    x = start_x
    while x < end_x:
        bar_width = random.choice([2, 4, 6, 8])
        if x + bar_width > end_x:
            break
        
        # Draw bar
        draw.rectangle([x, top_y, x + bar_width, bottom_y], fill=barcode_color)
        
        # Gap
        gap = random.choice([2, 4])
        x += bar_width + gap

    # Save PNG
    img.save('app_icon.png')
    
    # Save ICO
    img.save('app_icon.ico', format='ICO', sizes=[(256, 256)])
    print("Icons generated: app_icon.png, app_icon.ico")

if __name__ == '__main__':
    create_icon()
