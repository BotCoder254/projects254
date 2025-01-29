from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        # Add logo
        self.image('static/img/logo.png', 10, 8, 33)
        # Set font
        self.set_font('Arial', 'B', 20)
        # Move to the right
        self.cell(80)
        # Title
        self.cell(30, 10, 'Food Order Receipt', 0, 0, 'C')
        # Line break
        self.ln(20)
        
    def footer(self):
        # Position at 1.5 cm from bottom
        self.set_y(-15)
        # Arial italic 8
        self.set_font('Arial', 'I', 8)
        # Page number
        self.cell(0, 10, 'Page ' + str(self.page_no()) + '/{nb}', 0, 0, 'C')
        
    def add_item_row(self, item, quantity, price, total):
        self.cell(90, 10, item, 1)
        self.cell(30, 10, str(quantity), 1)
        self.cell(30, 10, f"${price:.2f}", 1)
        self.cell(40, 10, f"${total:.2f}", 1)
        self.ln() 