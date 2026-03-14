import axios from '@/plugins/axios'

export interface InstanceStatus {
  success: boolean
  message?: string
  error?: string
  error_code?: string
  instance_id?: string
  state?: 'pending' | 'running' | 'stopped' | 'stopping' | 'terminated'
  public_ip?: string
  private_ip?: string
  previous_state?: string
  current_state?: string
  instance_type?: string
  region?: string
}

export class AWSService {
  private static instance: AWSService

  static getInstance(): AWSService {
    if (!this.instance) {
      this.instance = new AWSService()
    }
    return this.instance
  }

  async getInstanceStatus(): Promise<InstanceStatus> {
    try {
      const response = await axios.get<InstanceStatus>('/api/aws/instance/status/')
      return response.data
    } catch (error) {
      console.error('Failed to get instance status:', error)
      throw error
    }
  }

  async startInstance(): Promise<InstanceStatus> {
    try {
      const response = await axios.post<InstanceStatus>('/api/aws/instance/start/')
      return response.data
    } catch (error) {
      console.error('Failed to start instance:', error)
      throw error
    }
  }

  async stopInstance(): Promise<InstanceStatus> {
    try {
      const response = await axios.post<InstanceStatus>('/api/aws/instance/stop/')
      return response.data
    } catch (error) {
      console.error('Failed to stop instance:', error)
      throw error
    }
  }

  async rebootInstance(): Promise<InstanceStatus> {
    try {
      const response = await axios.post<InstanceStatus>('/api/aws/instance/', {
        action: 'reboot',
      })
      return response.data
    } catch (error) {
      console.error('Failed to reboot instance:', error)
      throw error
    }
  }
}

export const awsService = AWSService.getInstance()
