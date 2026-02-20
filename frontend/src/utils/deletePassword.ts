const DEFAULT_DELETE_PASSWORD = '12356789'

export const getDeletePassword = () => {
  const fromEnv = import.meta.env.VITE_DELETE_PASSWORD
  if (typeof fromEnv === 'string' && fromEnv.trim().length > 0) {
    return fromEnv.trim()
  }
  return DEFAULT_DELETE_PASSWORD
}

