---
layout: default
title: Webex Contact Center BYOVA Gateway
---

# Webex Contact Center BYOVA Gateway

Welcome to the documentation for the Webex Contact Center BYOVA (Bring Your Own Virtual Agent) Gateway. This gateway enables seamless integration between Webex Contact Center and various virtual agent providers, including AWS Lex.

## 🚀 Quick Start

Get up and running in minutes with our comprehensive setup guide:

**[📖 Complete Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)**

This guide covers everything you need to know:
- Setting up a Webex Contact Center sandbox
- Configuring BYOVA and BYODS (Bring Your Own Data Source)
- Creating and configuring AWS Lex bots
- Deploying and testing the gateway

## 🏗️ What You'll Build

A fully functional voice AI system where customers can:
- Call your contact center
- Interact with an AWS Lex-powered virtual agent
- Seamlessly transfer to human agents when needed

## 🔧 Key Features

- **gRPC Integration**: Seamless communication with Webex Contact Center
- **Modular Architecture**: Easy to extend with new virtual agent providers
- **Real-time Monitoring**: Web dashboard for debugging and monitoring
- **Multiple Connectors**: Support for local audio testing and AWS Lex production
- **Comprehensive Logging**: Detailed logs for troubleshooting and analysis

## 📚 Documentation

- **[Customer Evaluation](CUSTOMER_EVALUATION.md)** - Determine whether BYOVA fits an existing voice-agent platform and plan a proof of concept
- **[Local Audio Connector Configuration](LOCAL_AUDIO_CONFIGURATION.md)** - Validate BYOVA with a Contact Center sandbox before choosing a voice-agent provider
- **[Local Development](LOCAL_DEVELOPMENT.md)** - Install, run, and troubleshoot the sample locally
- **[JWT Authentication](JWT_AUTHENTICATION.md)** - Configure Webex runtime token validation
- **[Testing](TESTING.md)** - Run automated, HTTP, gRPC, and end-to-end tests
- **[Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)** - Complete step-by-step setup
- **[Productization and Production Readiness Guide](PRODUCTION_READINESS.md)** - Requirements for operating a derivative of this sample at high call volume
- **[Protocol Definitions](https://github.com/webex/webex-byova-gateway-python/tree/main/proto)** - BYOVA and health protocol source files
- **[GitHub Repository](https://github.com/webex/webex-byova-gateway-python)** - Source code and issues

## 🛠️ Development

This gateway serves as a **functional example** for customers implementing BYOVA integrations. It demonstrates:

- Best practices for implementing BYOVA gRPC interfaces
- Modular architecture that can be adapted for different use cases
- Well-documented code that serves as a learning resource
- Extensible connector system for various voice agent services

## 📞 Support

For questions about BYOVA integration:
- Check the troubleshooting section in the setup guide
- Review the gateway logs and monitoring interface
- Consult the AWS Lex and Webex Contact Center documentation
- Reach out to the developer community for assistance

---

**Ready to get started?** [Begin with the Complete Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)
