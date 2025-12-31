"""Server model for game server status"""
from datetime import datetime
import json


class Server:
    """Server model for tracking game servers"""
    
    def __init__(self, id=None, name=None, host=None, port=None, rcon_port=None,
                 rcon_password=None, status='offline', active_players=0, 
                 max_players=0, game_day=0, created_at=None, updated_at=None):
        self.id = id
        self.name = name
        self.host = host
        self.port = port
        self.rcon_port = rcon_port
        self.rcon_password = rcon_password
        self.status = status
        self.active_players = active_players
        self.max_players = max_players
        self.game_day = game_day
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
    
    def to_dict(self, include_sensitive=False):
        """Convert server to dictionary"""
        data = {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'status': self.status,
            'active_players': self.active_players,
            'max_players': self.max_players,
            'game_day': self.game_day,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_sensitive:
            data['rcon_port'] = self.rcon_port
            data['rcon_password'] = self.rcon_password
        return data
    
    @staticmethod
    def create_table(conn):
        """Create servers table"""
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS servers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                host VARCHAR(255) NOT NULL,
                port INT NOT NULL,
                rcon_port INT,
                rcon_password VARCHAR(255),
                status VARCHAR(50) DEFAULT 'offline',
                active_players INT DEFAULT 0,
                max_players INT DEFAULT 0,
                game_day INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_name (name),
                INDEX idx_status (status)
            )
        ''')
        conn.commit()
    
    @staticmethod
    def find_by_id(conn, server_id):
        """Find server by ID"""
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM servers WHERE id = %s', (server_id,))
        row = cursor.fetchone()
        if row:
            return Server(**row)
        return None
    
    @staticmethod
    def find_by_name(conn, name):
        """Find server by name"""
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM servers WHERE name = %s', (name,))
        row = cursor.fetchone()
        if row:
            return Server(**row)
        return None
    
    def save(self, conn):
        """Save server to database"""
        cursor = conn.cursor()
        try:
            if self.id:
                # Update existing server
                cursor.execute('''
                    UPDATE servers 
                    SET name = %s, host = %s, port = %s, rcon_port = %s, 
                        rcon_password = %s, status = %s, active_players = %s,
                        max_players = %s, game_day = %s
                    WHERE id = %s
                ''', (self.name, self.host, self.port, self.rcon_port,
                      self.rcon_password, self.status, self.active_players,
                      self.max_players, self.game_day, self.id))
            else:
                # Insert new server
                cursor.execute('''
                    INSERT INTO servers (name, host, port, rcon_port, rcon_password,
                                       status, active_players, max_players, game_day)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (self.name, self.host, self.port, self.rcon_port,
                      self.rcon_password, self.status, self.active_players,
                      self.max_players, self.game_day))
                self.id = cursor.lastrowid
            conn.commit()
            return self
        finally:
            cursor.close()
    
    def delete(self, conn):
        """Delete server from database"""
        if self.id:
            cursor = conn.cursor()
            try:
                cursor.execute('DELETE FROM servers WHERE id = %s', (self.id,))
                conn.commit()
                return True
            finally:
                cursor.close()
        return False
    
    @staticmethod
    def get_all(conn, status=None, limit=100, offset=0):
        """Get all servers with optional status filter"""
        cursor = conn.cursor(dictionary=True)
        try:
            if status:
                cursor.execute(
                    'SELECT * FROM servers WHERE status = %s LIMIT %s OFFSET %s',
                    (status, limit, offset)
                )
            else:
                cursor.execute('SELECT * FROM servers LIMIT %s OFFSET %s', (limit, offset))
            rows = cursor.fetchall()
            return [Server(**row) for row in rows]
        finally:
            cursor.close()
        return [Server(**row) for row in rows]
