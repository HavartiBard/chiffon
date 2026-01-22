import { fireEvent, render, screen } from '@testing-library/react'
import ChatInterface from '../ChatInterface'
import { useChat } from '../../hooks/useChat'

type UseChatMock = ReturnType<typeof useChat>

vi.mock('../../hooks/useChat')
const mockedUseChat = vi.mocked(useChat)

const defaultState: UseChatMock = {
  session: null,
  messages: [],
  plan: null,
  isLoading: false,
  error: null,
  sendMessage: vi.fn(),
  clearHistory: vi.fn(),
}

beforeEach(() => {
  mockedUseChat.mockReturnValue(defaultState)
})

afterEach(() => {
  vi.resetAllMocks()
})

describe('ChatInterface', () => {
  it('renders welcome message initially', () => {
    render(<ChatInterface />)
    expect(screen.getByText(/Welcome to Chiffon/i)).toBeInTheDocument()
  })

  it('renders messages from hook', () => {
    mockedUseChat.mockReturnValueOnce({
      ...defaultState,
      messages: [
        { id: '1', sessionId: 'session', role: 'user', content: 'Hi', timestamp: 'now' },
        { id: '2', sessionId: 'session', role: 'assistant', content: 'Hello', timestamp: 'now' },
      ],
    })

    render(<ChatInterface />)
    expect(screen.getByText('Hi')).toBeInTheDocument()
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  it('submits message via sendMessage', () => {
    const sendMessage = vi.fn()
    mockedUseChat.mockReturnValueOnce({
      ...defaultState,
      sendMessage,
    })
    render(<ChatInterface />)

    const textarea = screen.getByPlaceholderText(/Describe your deployment request/i)
    fireEvent.change(textarea, { target: { value: 'Deploy Kuma' } })
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false })

    expect(sendMessage).toHaveBeenCalledWith('Deploy Kuma')
  })

  it('shows error when provided', () => {
    mockedUseChat.mockReturnValueOnce({
      ...defaultState,
      error: 'Oops',
    })

    render(<ChatInterface />)
    expect(screen.getByText('Oops')).toBeInTheDocument()
  })
})
