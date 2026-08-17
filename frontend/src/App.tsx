import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider } from '@/components/auth-provider'
import { ProtectedRoute } from '@/components/protected-route'
import { ChatLayout } from '@/pages/chat/layout'
import { ChatIndexPage } from '@/pages/chat/index'
import { ChatThreadPage } from '@/pages/chat/thread'
import { SignInPage } from '@/pages/sign-in'
import { SignUpPage } from '@/pages/sign-up'

export default function App() {
  return (
    <BrowserRouter>
      {/* Inside the router so auth-aware pages can redirect. */}
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<SignInPage />} />
          <Route path="/signup" element={<SignUpPage />} />

          <Route element={<ProtectedRoute />}>
            <Route path="/chat" element={<ChatLayout />}>
              <Route index element={<ChatIndexPage />} />
              <Route path=":threadId" element={<ChatThreadPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
