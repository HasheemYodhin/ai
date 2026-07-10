# Extension Icons

This directory should contain the following PNG icon files:

- `icon16.png`  (16x16)
- `icon48.png`  (48x48)
- `icon128.png` (128x128)

## Generating Icons

You can create simple placeholder icons using any image editor, or generate them programmatically:

### Using a canvas-based script (Node.js):
```js
const { createCanvas } = require('canvas');
const fs = require('fs');

[16, 48, 128].forEach(size => {
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext('2d');

  // Background
  ctx.fillStyle = '#1e1e2e';
  ctx.fillRect(0, 0, size, size);

  // Diamond shape
  ctx.fillStyle = '#cba6f7';
  ctx.beginPath();
  ctx.moveTo(size / 2, size * 0.15);
  ctx.lineTo(size * 0.85, size / 2);
  ctx.lineTo(size / 2, size * 0.85);
  ctx.lineTo(size * 0.15, size / 2);
  ctx.closePath();
  ctx.fill();

  const buffer = canvas.toBuffer('image/png');
  fs.writeFileSync(`icon${size}.png`, buffer);
});
```

### Or using ImageMagick:
```bash
for size in 16 48 128; do
  convert -size ${size}x${size} xc:#1e1e2e \
    -fill '#cba6f7' -draw "polygon $((size/2)),$((size*15/100)) $((size*85/100)),$((size/2)) $((size/2)),$((size*85/100)) $((size*15/100)),$((size/2))" \
    "icon${size}.png"
done
```

The icons use the dabba brand purple (#cba6f7) diamond on a dark background (#1e1e2e).
