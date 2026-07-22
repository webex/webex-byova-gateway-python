---
layout: default
title: Webex Contact Center BYOVA Gateway
---

# Webex Contact Center BYOVA Gateway

Welcome to the documentation for the Webex Contact Center BYOVA (Bring Your Own Virtual Agent) Gateway. This gateway enables seamless integration between Webex Contact Center and various virtual agent providers, including AWS Lex.

## 🚀 Quick Start

If you have a Webex Contact Center sandbox but have not chosen a voice-agent
provider, start with the bundled local audio connector:

**[📖 Local Audio Connector Configuration](LOCAL_AUDIO_CONFIGURATION.md)**

For an Amazon Lex integration, use the comprehensive setup guide:

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

- **[Local Audio Connector Configuration](LOCAL_AUDIO_CONFIGURATION.md)** - Vendor-neutral first test with a Contact Center sandbox
- **[Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)** - Complete step-by-step setup
- **[API Reference](api/)** - Detailed API documentation
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

**Not sure which voice-agent provider to use?** [Begin with the Local Audio Connector](LOCAL_AUDIO_CONFIGURATION.md).

**Using Amazon Lex?** [Follow the Complete Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex).
