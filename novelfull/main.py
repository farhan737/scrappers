from bs4 import BeautifulSoup

, encoding="utf-8") as file:
    soup = BeautifulSoup(file, "html.parser")

paragraphs = [
    p.get_text(" ", strip=True)
    for p in soup.find_all("p")
]

for paragraph in paragraphs:
    print(paragraph)
