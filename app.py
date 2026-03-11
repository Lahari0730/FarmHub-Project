import sys
import types

# --- FORCE FIX FOR PYTHON 3.13 CGI ERROR ---
# Satisfies requirements for libraries that still look for cgi.parse_header
if 'cgi' not in sys.modules:
    cgi_module = types.ModuleType('cgi')
    cgi_module.parse_header = lambda line: (line, {}) 
    sys.modules['cgi'] = cgi_module
# ------------------------------------------

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
from functools import wraps
from flask_babel import Babel, _ , lazy_gettext as _l
from deep_translator import GoogleTranslator 
from openai import OpenAI  # Using OpenAI SDK to connect to Groq
import os

app = Flask(__name__)

# Secret key and API key ni environment variables nundi teeskuntunnam
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_secret_key_for_local')
DB_NAME = 'farmhub.db'

# Groq API Configuration
# Cloud lo idhi 'GROQ_API_KEY' ane variable nundi logic teeskuntundi
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# ================= BABEL CONFIG =================
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'

def get_locale():
    return session.get('lang', request.accept_languages.best_match(['en', 'te']))

babel = Babel(app, locale_selector=get_locale)

# ================= TRANSLATION HELPER =================
def auto_translate(text):
    """Automatically translates input to both English and Telugu for DB storage"""
    if not text: return ""
    text = str(text).strip()
    try:
        if "|" in text: return text
        en_text = GoogleTranslator(source='auto', target='en').translate(text)
        te_text = GoogleTranslator(source='auto', target='te').translate(text)
        return f"{en_text}|{te_text}"
    except Exception as e:
        print(f"Translation Error: {e}")
        return f"{text}|{text}"

@app.template_filter('localize')
def localize_filter(value):
    """Jinja filter to extract either EN or TE part based on user session"""
    if not value: return ""
    val_str = str(value)
    if '|' not in val_str: return val_str 
    parts = val_str.split('|')
    if session.get('lang') == 'te' and len(parts) > 1:
        return parts[1].strip()
    return parts[0].strip()

# ================= DATABASE SETUP =================
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        name TEXT NOT NULL, 
        phone TEXT UNIQUE NOT NULL, 
        password TEXT NOT NULL, 
        role TEXT NOT NULL, 
        upi_id TEXT, 
        address TEXT)''')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        farmer_id INTEGER NOT NULL, 
        name TEXT NOT NULL, 
        category TEXT, 
        price REAL NOT NULL, 
        stock_kg INTEGER NOT NULL, 
        image_url TEXT, 
        FOREIGN KEY (farmer_id) REFERENCES users (id))''')

    cur.execute("PRAGMA table_info(products)")
    columns = [column[1] for column in cur.fetchall()]
    if 'image_url' not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
    
    cur.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        customer_id INTEGER NOT NULL, 
        product_id INTEGER NOT NULL, 
        quantity_kg INTEGER NOT NULL, 
        total_price REAL NOT NULL, 
        payment_method TEXT NOT NULL, 
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
        status TEXT DEFAULT 'Pending', 
        FOREIGN KEY (customer_id) REFERENCES users (id), 
        FOREIGN KEY (product_id) REFERENCES products (id))''')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS service_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        provider_id INTEGER NOT NULL, 
        service_type TEXT NOT NULL, 
        price_per_hour REAL NOT NULL, 
        description TEXT, 
        FOREIGN KEY (provider_id) REFERENCES users (id))''')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS service_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        farmer_id INTEGER NOT NULL, 
        provider_id INTEGER, 
        service_type TEXT NOT NULL, 
        details TEXT NOT NULL, 
        status TEXT DEFAULT 'Pending', 
        FOREIGN KEY (farmer_id) REFERENCES users (id), 
        FOREIGN KEY (provider_id) REFERENCES users (id))''')

    cur.execute('''CREATE TABLE IF NOT EXISTS service_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        request_id INTEGER NOT NULL,
        farmer_id INTEGER NOT NULL,
        rating INTEGER NOT NULL,
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (request_id) REFERENCES service_requests (id),
        FOREIGN KEY (farmer_id) REFERENCES users (id))''')

    conn.commit()
    conn.close()

# ================= ACCESS CONTROL =================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash(_('Please log in first.'), 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def farmer_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'farmer':
            flash(_('Access Restricted: This page is for farmers only.'), 'warning')
            return redirect(url_for('marketplace'))
        return f(*args, **kwargs)
    return wrapper

# ================= ROUTES =================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_lang/<lang_code>')
def set_language(lang_code):
    session['lang'] = lang_code
    return redirect(request.referrer or url_for('index'))

@app.route('/farming_guide')
@login_required
@farmer_required
def farming_guide():
    return render_template('farming_guide.html')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    user_id = session['user_id']
    
    if request.method == 'POST':
        new_name = request.form.get('name')
        new_address = request.form.get('address')
        new_upi = request.form.get('upi_id')
        
        conn.execute('''UPDATE users SET name = ?, address = ?, upi_id = ? 
                        WHERE id = ?''', (new_name, new_address, new_upi, user_id))
        conn.commit()
        
        session['name'] = new_name
        flash(_('Profile updated successfully!'), 'success')
        return redirect(url_for('profile'))

    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return render_template('profile.html', user=user)

# AI BOT ROUTE
@app.route('/ask_bot', methods=['POST'])
@login_required
def ask_bot():
    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"reply": "Please type a crop name."}), 400

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are a professional Agriculture Expert for Farm Hub. "
                        "When a user asks about a crop or plant, provide a clear, structured guide on how to grow it. "
                        "Include: 1. Soil & Climate, 2. Sowing, 3. Water/Fertilizer, 4. Pest Control, 5. Harvesting. "
                        "Support English and Telugu. Use bullet points."
                    )
                },
                {"role": "user", "content": f"Tell me the process to grow: {user_message}"}
            ]
        )
        return jsonify({"reply": completion.choices[0].message.content})
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"reply": "I'm having trouble connecting to the AI guide. Please try again later."})

@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('role')
    name = session.get('name')
    flash(_('Welcome back, %(name)s!', name=name), 'success')
    
    if role == 'farmer':
        return redirect(url_for('farmer_manage'))
    elif role == 'service_provider':
        return redirect(url_for('service_provider_dashboard'))
    return redirect(url_for('marketplace'))

@app.route('/farmer/manage')
@login_required
@farmer_required
def farmer_manage():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products WHERE farmer_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('farmer_manage.html', products=products)

@app.route('/farmer/add', methods=['GET', 'POST'])
@login_required
@farmer_required
def farmer_add():
    if request.method == 'POST':
        name = auto_translate(request.form.get('name'))
        category = auto_translate(request.form.get('category'))
        price = request.form.get('price')
        stock = request.form.get('stock')
        image_url = request.form.get('image_url')
        
        conn = get_db_connection()
        conn.execute('INSERT INTO products (farmer_id, name, category, price, stock_kg, image_url) VALUES (?, ?, ?, ?, ?, ?)',
                     (session['user_id'], name, category, price, stock, image_url))
        conn.commit()
        conn.close()
        flash(_('Product added successfully!'), 'success')
        return redirect(url_for('farmer_manage'))
    return render_template('farmer_add.html')

@app.route('/farmer/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@farmer_required
def edit_product(product_id):
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ? AND farmer_id = ?', 
                            (product_id, session['user_id'])).fetchone()

    if request.method == 'POST':
        name = auto_translate(request.form.get('name'))
        category = auto_translate(request.form.get('category'))
        price = request.form.get('price')
        stock = request.form.get('stock')
        image_url = request.form.get('image_url')

        conn.execute('''UPDATE products 
                        SET name = ?, category = ?, price = ?, stock_kg = ?, image_url = ? 
                        WHERE id = ? AND farmer_id = ?''',
                     (name, category, price, stock, image_url, product_id, session['user_id']))
        conn.commit()
        conn.close()
        flash(_('Product updated successfully!'), 'success')
        return redirect(url_for('farmer_manage'))
    
    conn.close()
    if not product:
        flash(_('Product not found.'), 'danger')
        return redirect(url_for('farmer_manage'))
    return render_template('farmer_edit.html', product=product)

@app.route('/farmer/delete/<int:product_id>')
@login_required
@farmer_required
def delete_product(product_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM products WHERE id = ? AND farmer_id = ?', (product_id, session['user_id']))
    conn.commit()
    conn.close()
    flash(_('Product removed.'), 'info')
    return redirect(url_for('farmer_manage'))

@app.route('/provider/dashboard')
@login_required
def service_provider_dashboard():
    conn = get_db_connection()
    user_id = session['user_id']
    
    my_listings = conn.execute('SELECT * FROM service_listings WHERE provider_id = ?', (user_id,)).fetchall()
    
    available = conn.execute('''SELECT sr.*, u.name as farmer_name, u.phone as farmer_phone 
                                FROM service_requests sr 
                                JOIN users u ON sr.farmer_id = u.id 
                                WHERE sr.status = "Pending"''').fetchall()
    
    my_tasks = conn.execute('''SELECT sr.*, u.name as farmer_name, u.phone as farmer_phone, u.address as farmer_address 
                               FROM service_requests sr 
                               JOIN users u ON sr.farmer_id = u.id 
                               WHERE sr.provider_id = ?''', (user_id,)).fetchall()
    conn.close()
    
    return render_template('service_provider_dashboard.html', my_listings=my_listings, available=available, my_tasks=my_tasks)

@app.route('/provider/add-listing', methods=['GET', 'POST'])
@login_required
def add_service_listing():
    if request.method == 'POST':
        service_type = auto_translate(request.form.get('service_type'))
        price = request.form.get('price_per_hour')
        description = auto_translate(request.form.get('description'))
        
        conn = get_db_connection()
        conn.execute('INSERT INTO service_listings (provider_id, service_type, price_per_hour, description) VALUES (?, ?, ?, ?)',
                     (session['user_id'], service_type, price, description))
        conn.commit()
        conn.close()
        flash(_('Service listing added successfully!'), 'success')
        return redirect(url_for('service_provider_dashboard'))
    return render_template('add_service_listing.html')

@app.route('/provider/accept-task/<int:request_id>')
@login_required
def accept_task(request_id):
    conn = get_db_connection()
    conn.execute('UPDATE service_requests SET provider_id = ?, status = "Accepted" WHERE id = ?',
                 (session['user_id'], request_id))
    conn.commit()
    conn.close()
    flash(_('Task accepted! Please contact the farmer.'), 'success')
    return redirect(url_for('service_provider_dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        password = request.form['password']
        role = request.form['role']
        upi_id = request.form.get('upi_id', '')
        address = request.form.get('address', '')
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (name, phone, password, role, upi_id, address) VALUES (?,?,?,?,?,?)', 
                         (name, phone, password, role, upi_id, address))
            conn.commit()
            flash(_('Registration successful! Please log in.'), 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash(_('Phone number already registered.'), 'danger')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE phone = ?', (phone,)).fetchone()
        conn.close()
        if user and user['password'] == password:
            session.update({'user_id': user['id'], 'name': user['name'], 'role': user['role']})
            return redirect(url_for('dashboard'))
        flash(_('Invalid phone number or password.'), 'danger')
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    return render_template('reset_password.html')

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        phone = request.form.get('phone')
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash(_('Passwords do not match!'), 'danger')
            return render_template('reset_password.html')

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE phone = ?', (phone,)).fetchone()
        
        if user:
            conn.execute('UPDATE users SET password = ? WHERE phone = ?', (new_password, phone))
            conn.commit()
            conn.close()
            flash(_('Password reset successful. Please log in.'), 'success')
            return redirect(url_for('login'))
        else:
            conn.close()
            flash(_('Phone number not found in our system.'), 'danger')
            return render_template('reset_password.html')
            
    return render_template('reset_password.html')

@app.route('/logout')
def logout():
    session.clear()
    flash(_('You have been logged out.'), 'info')
    return redirect(url_for('login'))

@app.route('/services')
@login_required
@farmer_required
def services():
    conn = get_db_connection()
    s_type = request.args.get('service_type', '')
    max_p = request.args.get('max_price', 99999)
    query = "SELECT sl.*, u.name as provider_name FROM service_listings sl JOIN users u ON sl.provider_id = u.id WHERE sl.price_per_hour <= ?"
    params = [max_p]
    if s_type:
        query += " AND sl.service_type LIKE ?"
        params.append(f"%{s_type}%")
    listings = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('services.html', listings=listings)

@app.route('/services/custom-request', methods=['GET', 'POST'])
@login_required
@farmer_required
def custom_request():
    if request.method == 'POST':
        service_type = auto_translate(request.form.get('service_type'))
        details = auto_translate(request.form.get('details'))
        conn = get_db_connection()
        conn.execute('INSERT INTO service_requests (farmer_id, service_type, details) VALUES (?, ?, ?)',
                     (session['user_id'], service_type, details))
        conn.commit()
        conn.close()
        flash(_('Service request submitted.'), 'success')
        return redirect(url_for('my_service_history'))
    return render_template('custom_request.html')

@app.route('/services/history')
@login_required
@farmer_required
def my_service_history():
    conn = get_db_connection()
    my_reqs = conn.execute('''SELECT sr.*, u.phone as provider_phone 
                                FROM service_requests sr 
                                LEFT JOIN users u ON sr.provider_id = u.id 
                                WHERE sr.farmer_id = ? ORDER BY sr.id DESC''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('my_service_history.html', requests=my_reqs)

@app.route('/services/complete/<int:request_id>')
@login_required
@farmer_required
def mark_service_complete(request_id):
    conn = get_db_connection()
    conn.execute('UPDATE service_requests SET status = "Completed" WHERE id = ? AND farmer_id = ?', 
                  (request_id, session['user_id']))
    conn.commit()
    conn.close()
    flash(_('Service marked as completed. Please leave a review!'), 'success')
    return redirect(url_for('my_service_history'))

@app.route('/services/feedback/<int:request_id>', methods=['POST'])
@login_required
@farmer_required
def submit_feedback(request_id):
    rating = request.form.get('rating')
    comment = request.form.get('comment')
    
    conn = get_db_connection()
    conn.execute('''INSERT INTO service_feedback (request_id, farmer_id, rating, comment) 
                    VALUES (?, ?, ?, ?)''', 
                 (request_id, session['user_id'], rating, comment))
    
    conn.execute('UPDATE service_requests SET status = "Completed" WHERE id = ?', (request_id,))
    
    conn.commit()
    conn.close()
    flash(_('Thank you for your feedback!'), 'success')
    return redirect(url_for('my_service_history'))

# ================= MARKETPLACE WITH FUZZY LOCATION MATCHING =================
# ================= MARKETPLACE WITH FUZZY LOCATION MATCHING =================
@app.route('/marketplace')
def marketplace():
    conn = get_db_connection()
    user_location = ""
    city_only = ""
    
    if 'user_id' in session:
        user = conn.execute('SELECT address FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if user and user['address']:
            user_location = user['address']
            # Extract just the first word/city for more flexible matching
            city_only = user_location.split(',')[0].strip()

    # We use city_only for the search to ensure it's not too restrictive
    products = conn.execute('''SELECT p.*, u.name AS farmer_name, u.address AS farmer_address 
                               FROM products p 
                               JOIN users u ON p.farmer_id = u.id 
                               WHERE p.stock_kg > 0
                               ORDER BY 
                               CASE 
                                 WHEN ? != "" AND u.address LIKE '%' || ? || '%' THEN 0 
                                 ELSE 1 
                               END, 
                               p.id DESC''', (city_only, city_only)).fetchall()
    conn.close()
    
    # Passing city_only to the template so it can display the "Nearby" badge
    return render_template('marketplace.html', products=products, user_location=city_only)

@app.route('/orders')
@login_required
def view_orders():
    conn = get_db_connection()
    role = session['role']
    if role == 'farmer':
        orders = conn.execute('''SELECT o.*, p.name as product_name, u.name as customer_name, u.address as customer_address 
                                  FROM orders o 
                                  JOIN products p ON o.product_id = p.id 
                                  JOIN users u ON o.customer_id = u.id 
                                  WHERE p.farmer_id = ? ORDER BY o.order_date DESC''', (session['user_id'],)).fetchall()
        template = 'farmer_orders.html'
    else:
        orders = conn.execute('''SELECT o.*, p.name as product_name, u.name as farmer_name 
                                  FROM orders o 
                                  JOIN products p ON o.product_id = p.id 
                                  JOIN users u ON p.farmer_id = u.id 
                                  WHERE o.customer_id = ? ORDER BY o.order_date DESC''', (session['user_id'],)).fetchall()
        template = 'customer_orders.html'
    conn.close()
    return render_template(template, orders=orders)

@app.route('/buy/<int:product_id>', methods=['POST'])
@login_required
def buy_product(product_id):
    qty = int(request.form.get('quantity', 1))
    pay_method = request.form.get('payment_method', 'COD')
    
    conn = get_db_connection()
    product = conn.execute('''SELECT p.*, u.name as farmer_name, u.upi_id 
                              FROM products p JOIN users u ON p.farmer_id = u.id 
                              WHERE p.id = ?''', (product_id,)).fetchone()
    
    if product and qty <= product['stock_kg']:
        total = qty * product['price']
        conn.execute('UPDATE products SET stock_kg = stock_kg - ? WHERE id = ?', (qty, product_id))
        conn.execute('''INSERT INTO orders (customer_id, product_id, quantity_kg, total_price, payment_method, status) 
                        VALUES (?,?,?,?,?,?)''', 
                     (session['user_id'], product_id, qty, total, pay_method, 'Pending'))
        conn.commit()
        conn.close()

        if pay_method == 'UPI':
            return render_template('upi_payment.html', 
                                    name=product['farmer_name'], 
                                    upi=product['upi_id'], 
                                    amount=total)
        
        flash(_('Order placed successfully!'), 'success')
        return redirect(url_for('view_orders'))
    
    conn.close()
    flash(_('Insufficient stock.'), 'danger')
    return redirect(url_for('marketplace'))

@app.route('/cancel_order/<int:order_id>')
@login_required
def cancel_order(order_id):
    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if order:
        conn.execute('UPDATE products SET stock_kg = stock_kg + ? WHERE id = ?', 
                     (order['quantity_kg'], order['product_id']))
        conn.execute('UPDATE orders SET status = "Cancelled" WHERE id = ?', (order_id,))
        conn.commit()
        flash(_('Order cancelled successfully.'), 'info')
    conn.close()
    return redirect(url_for('view_orders'))

@app.route('/update_order_status/<int:order_id>/<string:new_status>')
@login_required
def update_order_status(order_id, new_status):
    conn = get_db_connection()
    conn.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()
    flash(_('Order status updated!'), 'success')
    return redirect(url_for('view_orders'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)