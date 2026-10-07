/**
 * 部门管理 API
 */

import { apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

const BASE_URL = '/api/departments'

/**
 * 获取部门列表（普通管理员可访问）
 * @returns {Promise<Array>} 部门列表
 */
export const getDepartments = () => {
  return apiAdminGet(BASE_URL)
}

/**
 * 获取部门详情
 * @param {number} departmentId - 部门ID
 * @returns {Promise<Object>} 部门详情
 */
export const getDepartment = (departmentId) => {
  return apiAdminGet(`${BASE_URL}/${departmentId}`)
}

/**
 * 创建部门
 * @param {Object} data - 部门数据
 * @param {string} data.name - 部门名称
 * @param {string} [data.description] - 部门描述
 * @returns {Promise<Object>} 创建的部门
 */
export const createDepartment = (data) => {
  return apiAdminPost(BASE_URL, data)
}

/**
 * 更新部门
 * @param {number} departmentId - 部门ID
 * @param {Object} data - 部门数据
 * @param {string} [data.name] - 部门名称
 * @param {string} [data.description] - 部门描述
 * @returns {Promise<Object>} 更新后的部门
 */
export const updateDepartment = (departmentId, data) => {
  return apiAdminPut(`${BASE_URL}/${departmentId}`, data)
}

/**
 * 删除部门
 * @param {number} departmentId - 部门ID
 * @returns {Promise<Object>} 删除结果
 */
export const deleteDepartment = (departmentId) => {
  return apiAdminDelete(`${BASE_URL}/${departmentId}`)
}

export const departmentApi = {
  getDepartments,
  getDepartment,
  createDepartment,
  updateDepartment,
  deleteDepartment
}
