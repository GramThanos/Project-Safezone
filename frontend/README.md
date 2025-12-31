# Frontend Documentation

## Overview

The Project Safezone frontend is a modern React application with a dark themed UI, user authentication, player management, and admin panel capabilities.

## Architecture

The frontend is organized into multiple modules for maintainability:

```
frontend/
├── public/
│   ├── assets/
│   │   ├── style.css      # Custom CSS styles
│   │   └── images/        # Image assets
│   └── index.html         # HTML template
├── src/
│   ├── components/        # Reusable components
│   │   ├── Navbar.js      # Navigation bar
│   │   ├── Footer.js      # Footer component
│   │   └── ProtectedRoute.js  # Route protection
│   ├── pages/            # Page components
│   │   ├── Home.js        # Home page
│   │   ├── SignIn.js      # Authentication page
│   │   ├── Servers.js     # Server list page
│   │   ├── Players.js     # Player management page
│   │   ├── Profile.js     # User profile page
│   │   └── Admin.js       # Admin panel page
│   ├── context/          # React Context
│   │   └── AuthContext.js # Authentication context
│   ├── services/         # API services
│   │   └── api.js        # API client
│   ├── App.js            # Main app component
│   └── index.js          # Entry point
└── package.json          # Dependencies
```

## Features

- **Modern UI**: Dark theme with Bootstrap 5 and custom styling
- **User Authentication**: Sign in and sign up with JWT tokens
- **Protected Routes**: Automatic redirect for unauthenticated users
- **Player Management**: Create, edit, and delete game characters
- **Server Status**: Real-time server monitoring
- **Admin Panel**: Role-based admin interface for moderators and admins
- **Responsive Design**: Works on desktop and mobile devices

## Pages

### Home (`/`)
- Hero section with call-to-action
- Feature showcase
- Dynamic content based on authentication status

### Sign In (`/signin`)
- Combined sign in and sign up form
- Form validation
- Error handling
- Auto-redirect after successful authentication

### Servers (`/servers`)
- List of all game servers
- Real-time status updates
- Server statistics (players, game day)
- Auto-refresh every 30 seconds

### Players (`/players`) - Protected
- List of user's game characters
- Create new players
- Edit existing players
- Delete players
- Modal-based forms

### Profile (`/profile`) - Protected
- User information display
- Role badge
- Account details

### Admin Panel (`/admin`) - Protected (Moderator/Admin)
- Tabbed interface
- Servers management
- Tasks monitoring
- User management (Admin only)
- Role-based visibility

## Components

### Navbar
- Responsive navigation
- Dynamic menu based on user role
- Authentication status

### Footer
- Site information
- Social media links
- Copyright notice

### ProtectedRoute
- HOC for route protection
- Automatic redirect to sign in
- Loading state handling

## State Management

### AuthContext
Provides authentication state and methods:
- `user` - Current user object
- `token` - JWT token
- `loading` - Loading state
- `signin(username, password)` - Sign in method
- `signup(username, email, password)` - Sign up method
- `signout()` - Sign out method
- `isAdmin()` - Check admin role
- `isModerator()` - Check moderator role

## API Service

The `api.js` service provides methods for all backend endpoints:

```javascript
// Authentication
api.auth.signin(username, password)
api.auth.signup(username, email, password)
api.auth.me(token)

// Players
api.players.getAll(token)
api.players.get(token, id)
api.players.create(token, data)
api.players.update(token, id, data)
api.players.delete(token, id)

// Servers
api.servers.getAll()
api.servers.getStatus()

// Admin
api.admin.users.getAll(token)
api.admin.users.updateRole(token, userId, role)
api.admin.servers.getAll(token)
api.admin.servers.create(token, data)
api.admin.servers.update(token, id, data)
api.admin.servers.delete(token, id)
api.admin.tasks.getAll(token)
api.admin.tasks.create(token, data)
```

## Styling

The application uses:
- **Bootstrap 5** for layout and components
- **Custom CSS** (`assets/style.css`) for theme
- **Font Awesome** for icons
- **Google Fonts** (Oswald & Roboto)

### Color Scheme
- Background: Dark gradients (#0b0d0f to #0d0f10)
- Accent: Red (#e32020)
- Text: Light gray (#e6e6e6)
- Cards: Subtle gray (#111214)

## Setup

### Environment Variables

Create `.env` file in frontend directory:

```bash
REACT_APP_API_URL=http://localhost:5000
```

For production, set to your backend URL.

### Installation

```bash
# Install dependencies
npm install

# Start development server
npm start

# Build for production
npm run build
```

## Development

The app runs on `http://localhost:3000` in development mode.

API requests are proxied to the backend through the `proxy` setting in `package.json`.

## Routing

- `/` - Home (public)
- `/signin` - Sign in/Sign up (public)
- `/servers` - Server list (public)
- `/players` - Player management (protected)
- `/profile` - User profile (protected)
- `/admin` - Admin panel (protected, moderator/admin only)

## User Flow

1. **New User**:
   - Visit home page
   - Click "Sign In"
   - Switch to "Sign Up"
   - Create account
   - Redirected to home (authenticated)

2. **Existing User**:
   - Visit home page
   - Click "Sign In"
   - Enter credentials
   - Redirected to home (authenticated)

3. **Player Management**:
   - Click "My Players"
   - Create new player
   - Edit/Delete existing players

4. **Admin**:
   - Access "Admin Panel"
   - View servers, tasks, users
   - Manage system resources

## Browser Support

- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

## Performance

- Code splitting with React Router
- Lazy loading of routes
- Optimized images
- Minimal external dependencies
