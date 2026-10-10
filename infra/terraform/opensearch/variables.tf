variable "scheme" {
  type    = string
  default = "https"
}

variable "host" {
  type        = string
  description = "Private OpenSearch hostname supplied by the selected cloud implementation."
}

variable "port" {
  type    = number
  default = 443
}

variable "index_alias" {
  type    = string
  default = "compass-support-search"
}
