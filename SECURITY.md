# Security Implementation Guide

## Overview

The Project Safezone backend implements multiple layers of security to protect against common web vulnerabilities and ensure safe operation.

## Security Features

### 1. Anti-CSRF Protection

**JWT in Authorization Headers (Not Cookies)**
- JWTs are transmitted via Authorization headers instead of cookies
- This provides natural CSRF protection since browsers don't automatically send custom headers
- Cross-origin requests cannot read or set Authorization headers due to CORS

**Why CSRF Protection is Not Needed:**
- CSRF attacks rely on cookies being automatically sent by the browser
- Since we use JWT in headers, CSRF attacks are ineffective
- The frontend explicitly sets the Authorization header on each request

### 2. Access Control (Authorization)

**Role-Based Access Control (RBAC)**
- Four user roles: `banned`, `player`, `moderator`, `admin`
- Hierarchical permissions system
- Decorator-based access control

**Decorators:**
```python
@token_required         # Requires valid JWT token (any authenticated user)
@moderator_required     # Requires moderator or admin role
@admin_required         # Requires admin role only
```

**Access Matrix:**
| Endpoint | Public | Player | Moderator | Admin |
|----------|--------|--------|-----------|-------|
| `/api/auth/*` | ✅ | ✅ | ✅ | ✅ |
| `/api/servers` (GET) | ✅ | ✅ | ✅ | ✅ |
| `/api/players` | ❌ | ✅ | ✅ | ✅ |
| `/api/admin/users` | ❌ | ❌ | ✅ | ✅ |
| `/api/admin/servers` (GET) | ❌ | ❌ | ✅ | ✅ |
| `/api/admin/servers` (POST/PUT/DELETE) | ❌ | ❌ | ❌ | ✅ |
| `/api/admin/tasks` | ❌ | ❌ | ✅ | ✅ |

### 3. Lightweight JWT Tokens

**Minimal Payload:**
```json
{
  "user_id": 123,
  "username": "player1",
  "role": "player",
  "exp": 1735678800,
  "iat": 1735592400,
  "iss": "safezone-api",
  "aud": "safezone-frontend",
  "jti": "uuid-for-revocation"
}
```

**JWT Security Features:**
- **HS256 Algorithm**: Industry-standard HMAC-SHA256
- **Expiration (exp)**: 24 hours by default (configurable)
- **Issued At (iat)**: Timestamp of token creation
- **Issuer (iss)**: Validates token source
- **Audience (aud)**: Validates token destination
- **JWT ID (jti)**: Unique identifier for token revocation
- **Minimal claims**: Only essential data (no sensitive info)

**Token Verification:**
- Signature verification using SECRET_KEY
- Expiration check
- Issuer validation
- Audience validation
- Required claims validation

### 4. Rate Limiting

**Global Limits:**
- 200 requests per day per IP
- 50 requests per hour per IP

**Endpoint-Specific Limits:**
- `/api/auth/signin`: 5 requests per minute (brute-force protection)
- `/api/auth/signup`: 3 requests per hour (spam prevention)

**Storage:**
- Redis-backed for distributed rate limiting
- Survives application restarts

### 5. CORS (Cross-Origin Resource Sharing)

**Restricted Origins:**
- Configurable via `ALLOWED_ORIGINS` environment variable
- Default: `http://localhost:3000`
- Multiple origins supported (comma-separated)

**Configuration:**
```python
CORS(app, 
     origins=allowed_origins,
     supports_credentials=True,
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'])
```

### 6. Security Headers

**Implemented Headers:**
- `X-Frame-Options: DENY` - Prevents clickjacking
- `X-Content-Type-Options: nosniff` - Prevents MIME sniffing
- `X-XSS-Protection: 1; mode=block` - XSS protection
- `Content-Security-Policy: default-src 'self'` - Restricts resource loading
- `Strict-Transport-Security` - Forces HTTPS (when enabled)
- `Referrer-Policy: strict-origin-when-cross-origin` - Protects referrer info
- `Permissions-Policy` - Restricts browser features

### 7. Input Validation

**Authentication:**
- Username: 3-80 characters
- Password: Minimum 8 characters
- Email: Valid format (validated by SQLAlchemy)

**Data Sanitization:**
- SQLAlchemy ORM prevents SQL injection
- JSON parsing prevents injection attacks
- Avatar URLs validated in frontend

### 8. Password Security

**Hashing:**
- Werkzeug's `generate_password_hash()` and `check_password_hash()`
- Uses PBKDF2-SHA256 by default
- Salt automatically generated per password
- Configurable iterations

**Best Practices:**
- Passwords never stored in plain text
- Never logged or transmitted in responses
- Generic error messages (don't reveal if user exists)

### 9. Session Management

**JWT-Based Sessions:**
- Stateless authentication (no server-side sessions)
- Tokens stored in localStorage (frontend)
- Token sent via Authorization header
- Automatic expiration after configured time

**Token Refresh:**
- Currently not implemented (tokens expire after 24h)
- Users must re-authenticate after expiration
- Consider implementing refresh tokens for production

## Security Best Practices

### For Production Deployment:

1. **Environment Variables:**
   - Set strong `SECRET_KEY` (min 32 random characters)
   - Configure `ALLOWED_ORIGINS` to production domains
   - Enable `HTTPS_ENABLED=true`
   - Set `FLASK_DEBUG=false`

2. **HTTPS/TLS:**
   - Always use HTTPS in production
   - Configure valid SSL certificates
   - Enable HSTS header

3. **Database:**
   - Use strong database passwords
   - Restrict database access to backend only
   - Enable database connection encryption

4. **Monitoring:**
   - Log authentication failures
   - Monitor rate limit violations
   - Track admin actions
   - Set up alerts for suspicious activity

5. **Updates:**
   - Keep all dependencies updated
   - Monitor security advisories
   - Apply security patches promptly

## Threat Mitigation

| Threat | Mitigation |
|--------|-----------|
| SQL Injection | SQLAlchemy ORM with parameterized queries |
| XSS (Cross-Site Scripting) | CSP headers, output encoding, React's built-in protection |
| CSRF | JWT in headers (not cookies) |
| Brute Force | Rate limiting on auth endpoints |
| Session Hijacking | Short-lived JWT tokens, secure transmission |
| Clickjacking | X-Frame-Options header |
| MIME Sniffing | X-Content-Type-Options header |
| Man-in-the-Middle | HTTPS/TLS (in production) |
| Privilege Escalation | Role-based access control with validation |
| DDoS | Rate limiting, Redis connection pooling |

## Testing Security

```bash
# Test rate limiting
for i in {1..10}; do curl -X POST http://localhost:5000/api/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}'; done

# Test JWT validation
curl http://localhost:5000/api/players \
  -H "Authorization: Bearer invalid_token"

# Test CORS
curl http://localhost:5000/api/servers \
  -H "Origin: http://malicious-site.com" \
  -v

# Test role-based access
curl http://localhost:5000/api/admin/users \
  -H "Authorization: Bearer player_token"
```

## Security Audit Checklist

- [x] JWT tokens are lightweight (< 500 bytes)
- [x] JWT contains only necessary claims
- [x] JWT expiration is configured
- [x] JWT signature is verified
- [x] Rate limiting on authentication endpoints
- [x] Role-based access control on all protected endpoints
- [x] CORS restricted to known origins
- [x] Security headers on all responses
- [x] Passwords hashed with strong algorithm
- [x] SQL injection prevented via ORM
- [x] Input validation on all user inputs
- [x] Error messages don't leak sensitive info
- [x] Logging configured for security events
- [ ] Refresh token mechanism (optional)
- [ ] Token revocation system (optional)
- [ ] Two-factor authentication (future enhancement)

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [Flask Security](https://flask.palletsprojects.com/en/3.0.x/security/)
