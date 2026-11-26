import { useState, useRef } from 'react';
import { Upload, FileText, CheckCircle, X } from 'lucide-react';

export default function FileUpload({ onFileSelect, acceptedTypes = '.pdf,.docx', className = '' }) {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState(null);
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);
  const uploadInProgress = useRef(false);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleFile = async (selectedFile) => {
    // Guard: prevent duplicate concurrent uploads
    if (uploadInProgress.current) {
      console.warn('[FileUpload] Upload already in progress — ignoring duplicate call');
      return;
    }
    if (!/\.(pdf|docx)$/i.test(selectedFile.name) || selectedFile.size === 0 || selectedFile.size > 10 * 1024 * 1024) {
      setError('Choose a nonempty PDF or DOCX file of 10 MB or less.');
      return;
    }
    uploadInProgress.current = true;

    setFile(selectedFile);
    setParsed(false);
    setError('');
    setParsing(true);
    try {
      await onFileSelect?.(selectedFile);
      setParsed(true);
    } catch (selectionError) {
      setError(selectionError.message || 'Resume parsing failed.');
    } finally {
      setParsing(false);
      uploadInProgress.current = false;
    }
  };

  const clearFile = () => {
    if (uploadInProgress.current) return;
    setFile(null);
    setParsed(false);
    setError('');
    onFileSelect?.(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  if (file) {
    return (
      <div className={`glass-card p-6 ${className}`}>
        <div className="flex items-center gap-4">
          <div className="p-3 rounded-lg bg-selected">
            <FileText className="w-6 h-6 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-heading truncate">{file.name}</p>
            <div className="flex items-center gap-2 mt-1">
              {parsing ? <Upload className="w-3.5 h-3.5 text-primary animate-pulse" /> : <CheckCircle className="w-3.5 h-3.5 text-success" />}
              <span className={`text-xs ${error ? 'text-danger' : parsing ? 'text-primary' : 'text-success'}`}>
                {error || (parsing ? 'Parsing resume...' : parsed ? 'Parsed successfully' : 'Uploaded successfully')}
              </span>
              <span className="text-xs text-secondary">
                {file.size ? `${(file.size / 1024).toFixed(0)} KB` : ''}
              </span>
            </div>
          </div>
          <button
            onClick={clearFile}
            disabled={parsing}
            aria-label="Remove resume"
            className="min-h-11 min-w-11 grid place-items-center text-secondary hover:text-heading hover:bg-subtle rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      {error && <p role="alert" className="text-sm text-danger mb-3">{error}</p>}
      <input
        ref={inputRef}
        type="file"
        accept={acceptedTypes}
        onChange={(e) => {
          if (e.target.files && e.target.files[0]) {
            const selected = e.target.files[0];
            e.target.value = '';
            handleFile(selected);
          }
        }}
        className="hidden"
      />
      <div
        className={`relative border-2 border-dashed rounded-lg p-8 text-center transition-all duration-200 cursor-pointer
          ${dragActive
            ? 'border-primary bg-selected'
            : 'border-line hover:border-line hover:bg-subtle'
          }`}
        role="button"
        tabIndex={0}
        aria-label="Upload your resume"
        onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.currentTarget.click(); } }}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => {
          if (!uploadInProgress.current && !parsing) {
            inputRef.current?.click();
          }
        }}
      >
        <Upload className="w-8 h-8 text-primary mx-auto mb-4" />
        <p className="text-heading font-medium mb-1">Upload your resume</p>
        <p className="text-sm text-secondary">PDF or DOCX — Drag and drop or click to browse</p>
      </div>
    </div>
  );
}

