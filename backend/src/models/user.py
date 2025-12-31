"""User model"""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


class User:
    """User model for authentication and authorization"""
    
    ROLE_BANNED = 'banned'
    ROLE_PLAYER = 'player'
    ROLE_MODERATOR = 'moderator'
    ROLE_ADMIN = 'admin'
    
    ROLES = [ROLE_BANNED, ROLE_PLAYER, ROLE_MODERATOR, ROLE_ADMIN]
    
    def __init__(self, id=None, username=None, email=None, password_hash=None, 
                 role=ROLE_PLAYER, created_at=None):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.created_at = created_at or datetime.utcnow()
    
    def set_password(self, password):
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches hash"""
        return check_password_hash(self.password_hash, password)
    
    def is_admin(self):
        """Check if user is admin"""
        return self.role == self.ROLE_ADMIN
    
    def is_moderator(self):
        """Check if user is moderator or admin"""
        return self.role in [self.ROLE_MODERATOR, self.ROLE_ADMIN]
    
    def is_banned(self):
        """Check if user is banned"""
        return self.role == self.ROLE_BANNED
    
    def to_dict(self, include_sensitive=False):
        """Convert user to dictionary"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_sensitive:
            data['password_hash'] = self.password_hash
        return data
    
    @staticmethod
    def create_table(conn):
        """Create users table"""
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(80) UNIQUE NOT NULL,
                email VARCHAR(120) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'player',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_username (username),
                INDEX idx_email (email),
                INDEX idx_role (role)
            )
        ''')
        conn.commit()
    
    @staticmethod
    def find_by_id(conn, user_id):
        """Find user by ID"""
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        row = cursor.fetchone()
        if row:
            return User(**row)
        return None
    
    @staticmethod
    def find_by_username(conn, username):
        """Find user by username"""
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        row = cursor.fetchone()
        if row:
            return User(**row)
        return None
    
    @staticmethod
    def find_by_email(conn, email):
        """Find user by email"""
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        row = cursor.fetchone()
        if row:
            return User(**row)
        return None
    
    def save(self, conn):
        """Save user to database"""
        cursor = conn.cursor()
        if self.id:
            # Update existing user
            cursor.execute('''
                UPDATE users 
                SET username = %s, email = %s, password_hash = %s, role = %s
                WHERE id = %s
            ''', (self.username, self.email, self.password_hash, self.role, self.id))
        else:
            # Insert new user
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
            ''', (self.username, self.email, self.password_hash, self.role))
            self.id = cursor.lastrowid
        conn.commit()
        return self
    
    @staticmethod
    def get_all(conn, role=None, limit=100, offset=0):
        """Get all users with optional role filter"""
        cursor = conn.cursor(dictionary=True)
        if role:
            cursor.execute(
                'SELECT * FROM users WHERE role = %s LIMIT %s OFFSET %s',
                (role, limit, offset)
            )
        else:
            cursor.execute('SELECT * FROM users LIMIT %s OFFSET %s', (limit, offset))
        rows = cursor.fetchall()
        return [User(**row) for row in rows]
