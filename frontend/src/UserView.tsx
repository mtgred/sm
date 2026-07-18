import type { User } from "./interfaces"

const UserView: React.FC<{ user: User; color?: string }> = ({ user, color }) => (
  <div className="group inline-flex items-center gap-0.5 align-middle font-semibold">
    <img className="avatar" src={`https://www.gravatar.com/avatar/${user.hash}?d=retro&s=22`} />
    <div style={color ? { color } : undefined}>{user.username}</div>
  </div>
)

export default UserView
