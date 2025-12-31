"""Player (game character) model"""
from datetime import datetime
import json


class Player:
    """Player model for managing game characters"""
    
    def __init__(self, id=None, user_id=None, name=None, description=None, 
                 avatar=None, stats=None, created_at=None, updated_at=None):
        self.id = id
        self.user_id = user_id
        self.name = name
        self.description = description
        self.avatar = avatar
        self.stats = stats or {}
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
    
    def to_dict(self):
        """Convert player to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'description': self.description,
            'avatar': self.avatar,
            'stats': self.stats,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @staticmethod
    def create_table(conn):
        """Create players table"""
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                avatar VARCHAR(255),
                stats JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_user_id (user_id),
                INDEX idx_name (name)
            )
        ''')
        conn.commit()
    
    @staticmethod
    def find_by_id(conn, player_id):
        """Find player by ID"""
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM players WHERE id = %s', (player_id,))
        row = cursor.fetchone()
        if row:
            return Player(**row)
        return None
    
    @staticmethod
    def find_by_user(conn, user_id, limit=100, offset=0):
        """Find all players for a user"""
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            'SELECT * FROM players WHERE user_id = %s LIMIT %s OFFSET %s',
            (user_id, limit, offset)
        )
        rows = cursor.fetchall()
        return [Player(**row) for row in rows]
    
    def save(self, conn):
        """Save player to database"""
        cursor = conn.cursor()
        try:
            if self.id:
                # Update existing player
                cursor.execute('''
                    UPDATE players 
                    SET name = %s, description = %s, avatar = %s, stats = %s
                    WHERE id = %s
                ''', (self.name, self.description, self.avatar, 
                      json.dumps(self.stats) if self.stats else '{}', self.id))
            else:
                # Insert new player
                cursor.execute('''
                    INSERT INTO players (user_id, name, description, avatar, stats)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (self.user_id, self.name, self.description, self.avatar,
                      json.dumps(self.stats) if self.stats else '{}'))
                self.id = cursor.lastrowid
            conn.commit()
            return self
        finally:
            cursor.close()
    
    def delete(self, conn):
        """Delete player from database"""
        if self.id:
            cursor = conn.cursor()
            try:
                cursor.execute('DELETE FROM players WHERE id = %s', (self.id,))
                conn.commit()
                return True
            finally:
                cursor.close()
        return False
    
    @staticmethod
    def get_all(conn, limit=100, offset=0):
        """Get all players"""
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute('SELECT * FROM players LIMIT %s OFFSET %s', (limit, offset))
            rows = cursor.fetchall()
            return [Player(**row) for row in rows]
        finally:
            cursor.close()
