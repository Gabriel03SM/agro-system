"""Gera os ícones da PWA a partir de formas vetoriais simples da marca."""
from pathlib import Path

from PIL import Image, ImageDraw

saida = Path(__file__).resolve().parents[1] / "static" / "icons"
saida.mkdir(parents=True, exist_ok=True)
imagem = Image.new("RGB", (1024, 1024), "#2f6b3a")
desenho = ImageDraw.Draw(imagem)
desenho.line([(512, 820), (512, 230)], fill="#ffffff", width=20)
for y in (310, 420, 530, 640):
    desenho.polygon([(502, y + 70), (375, y + 20), (345, y - 75), (445, y - 35)], fill="#ffffff")
    desenho.polygon([(522, y + 70), (649, y + 20), (679, y - 75), (579, y - 35)], fill="#ffffff")
desenho.polygon([(512, 320), (465, 230), (512, 160), (559, 230)], fill="#ffffff")
for tamanho in (192, 512):
    imagem.resize((tamanho, tamanho), Image.Resampling.LANCZOS).save(saida / f"agro-{tamanho}.png")
print("Ícones 192 e 512 gerados.")
