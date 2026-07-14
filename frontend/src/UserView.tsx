import type { User } from "./interfaces"

const UserView: React.FC<{ user: User; color?: string }> = ({ user, color }) => (
  <div className="group space-x-1 font-semibold inline">
    <img className="avatar" src={`https://www.gravatar.com/avatar/${user.hash}?d=retro&s=22`} />
    <div style={color ? { color } : undefined}>{user.username}</div>
  </div>
)

export default UserView
