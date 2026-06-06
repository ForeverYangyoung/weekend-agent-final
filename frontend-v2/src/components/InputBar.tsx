import { useState, useRef, type KeyboardEvent } from 'react'

interface Props {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export function InputBar({ onSend, disabled, placeholder }: Props) {
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  function handleSend() {
    if (!text.trim() || disabled) return
    onSend(text.trim())
    setText('')
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function handleInput() {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 96) + 'px'
  }

  return (
    <div className="input-bar">
      <div className="input-row">
        <textarea
          ref={inputRef}
          className="input-field"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            handleInput()
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? '说说你的需求...'}
          disabled={disabled}
          rows={1}
        />
        <button
          className="send-btn"
          onClick={handleSend}
          disabled={disabled || !text.trim()}
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path
              d="M2 10l16-8-8 16-2-5-6-3z"
              fill={disabled || !text.trim() ? '#CCC' : '#fff'}
              stroke="none"
            />
          </svg>
        </button>
      </div>
      <div className="input-hint">
        输入"选择"进入偏好模式 · Enter 发送
      </div>
    </div>
  )
}
