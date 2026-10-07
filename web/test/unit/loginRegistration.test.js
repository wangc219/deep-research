import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const loginSource = readFileSync(new URL('../../src/views/LoginView.vue', import.meta.url), 'utf8')
const authApiSource = readFileSync(new URL('../../src/apis/auth_api.js', import.meta.url), 'utf8')

test('登录页提供统一用户体系的注册交互', () => {
  assert.match(loginSource, /authMode === 'register'/)
  assert.match(loginSource, /userStore\.register/)
  assert.match(loginSource, /label="所属部门"/)
  assert.match(loginSource, /registrationDepartmentOptions/)
  assert.match(loginSource, /department_id: registerForm\.department_id/)
  assert.match(authApiSource, /\/api\/auth\/registration-config/)
  assert.match(authApiSource, /\/api\/auth\/register/)
})

test('确认密码空值只由 required 规则提示一次', () => {
  assert.match(
    loginSource,
    /const validateConfirmPassword = async[\s\S]*?if \(!value\) return[\s\S]*?const validateRegisterConfirmPassword/
  )
  assert.match(
    loginSource,
    /const validateRegisterConfirmPassword = async[\s\S]*?if \(!value\) return/
  )
})

test('登录页默认使用装备创新主视觉', () => {
  assert.match(loginSource, /const loginBgImage = '\/equipment-login-hero\.png'/)
  assert.equal(existsSync(new URL('../../public/equipment-login-hero.png', import.meta.url)), true)
  assert.match(loginSource, /\.hero-art[\s\S]*object-fit:\s*cover/)
  assert.match(loginSource, /@media \(max-aspect-ratio: 8 \/ 5\)[\s\S]*object-fit:\s*contain/)
  assert.match(
    loginSource,
    /\.login-main[\s\S]*align-items:\s*center[\s\S]*justify-content:\s*center/
  )
  assert.doesNotMatch(loginSource, /<nav class="login-navbar"/)
  assert.doesNotMatch(loginSource, /<section class="hero-copy"/)
})
