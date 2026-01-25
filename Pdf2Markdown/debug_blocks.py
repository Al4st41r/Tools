import fitz

def inspect_blocks(pdf_path):
    doc = fitz.open(pdf_path)
    for page in doc:
        blocks = page.get_text("blocks")
        for i, b in enumerate(blocks[:20]):
            print(f"Block {i}: {repr(b[4])}")

if __name__ == "__main__":
    inspect_blocks("test/column_test-1.pdf")
