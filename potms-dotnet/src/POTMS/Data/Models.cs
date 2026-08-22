namespace POTMS.Data;

// 实体记录 —— 列名 snake_case 由 Dapper 的 MatchNamesWithUnderscores 自动映射到 PascalCase。
// 全部字段可空以容忍历史数据，与其它三版「读时宽容、写时校验」的口径一致。
//
// 注意：此处一律用「属性式 record」而非位置式（主构造函数）record。
// Dapper 对属性式走 setter 并做类型转换；对位置式则要求构造函数签名类型
// 与 SQLite 返回类型精确匹配（INTEGER → Int64），int 会导致物化失败。

public record PersonnelInfo
{
    public long Id { get; init; }
    public string? Unit { get; init; }
    public string? Department { get; init; }
    public string? Name { get; init; }
    public string? Gender { get; init; }
    public string? BirthDate { get; init; }
    public string? IdNumber { get; init; }
    public string? WorkStartDate { get; init; }
    public string? Education { get; init; }
    public string? Degree { get; init; }
    public string? Title { get; init; }
    public string? Rank { get; init; }
    public string? PoliticalStatus { get; init; }
    public string? PartyJoinDate { get; init; }
    public string? Position { get; init; }
    public string? Operator { get; init; }
    public string? CreatedAt { get; init; }
    public string? UpdatedAt { get; init; }
    public int FilingCount { get; init; }          // 关联备案数（信息表管理页用）
}

public record PersonnelFiling
{
    public long Id { get; init; }
    public long? PersonnelInfoId { get; init; }
    public string? Surname { get; init; }
    public string? GivenName { get; init; }
    public string? Gender { get; init; }
    public string? BirthDate { get; init; }
    public string? IdNumber { get; init; }
    public string? Residence { get; init; }
    public string? PoliticalStatus { get; init; }
    public string? WorkUnit { get; init; }
    public string? PositionOrTitle { get; init; }
    public string? SupervisorUnit { get; init; }
    public string? Tag { get; init; }
    public string? Informed { get; init; }
    public string? Status { get; init; }
    public string? Remarks { get; init; }
    public long? ReplacedById { get; init; }
    public string? Operator { get; init; }
    public string? CreatedAt { get; init; }
    public string? UpdatedAt { get; init; }
    public string Name => $"{Surname}{GivenName}";
}

public record Certificate
{
    public long Id { get; init; }
    public long PersonnelFilingId { get; init; }
    public string? Unit { get; init; }
    public string? Department { get; init; }
    public string? Name { get; init; }
    public string? PassportNo { get; init; }
    public string? PassportExpiry { get; init; }
    public string? PassportSubmitDate { get; init; }
    public string? HmPassNo { get; init; }
    public string? HmPassExpiry { get; init; }
    public string? HmPassSubmitDate { get; init; }
    public string? TwPassNo { get; init; }
    public string? TwPassExpiry { get; init; }
    public string? TwPassSubmitDate { get; init; }
    public string? Operator { get; init; }
    public string? CreatedAt { get; init; }
    public string? UpdatedAt { get; init; }
}

public record TravelDetail
{
    public long Id { get; init; }
    public long PersonnelFilingId { get; init; }
    public string? Unit { get; init; }
    public string? Department { get; init; }
    public string? Name { get; init; }
    public string? Position { get; init; }
    public string? Title { get; init; }
    public string? IdNumber { get; init; }
    public string? DestinationPassport { get; init; }
    public string? Category { get; init; }
    public string? TravelDates { get; init; }
    public string? TravelStart { get; init; }
    public string? TravelEnd { get; init; }
    public string? ApprovalDate { get; init; }
    public string? NeedNewPassport { get; init; }
    public string? PassportNo { get; init; }
    public string? PassportCollectDate { get; init; }
    public string? PassportReturnDate { get; init; }
    public string? ActualReturnDate { get; init; }
    public string? TripStatus { get; init; }
    public string? CancelDate { get; init; }
    public string? Operator { get; init; }
    public string? CreatedAt { get; init; }
    public string? UpdatedAt { get; init; }
}

public record DecontrolFiling
{
    public long Id { get; init; }
    public long PersonnelFilingId { get; init; }
    public string? Surname { get; init; }
    public string? GivenName { get; init; }
    public string? Gender { get; init; }
    public string? BirthDate { get; init; }
    public string? IdNumber { get; init; }
    public string? Residence { get; init; }
    public string? PoliticalStatus { get; init; }
    public string? WorkUnit { get; init; }
    public string? SupervisorUnit { get; init; }
    public string? SubmitUnitName { get; init; }
    public string? SubmitUnitType { get; init; }
    public string? SubmitContact { get; init; }
    public string? SubmitPhone { get; init; }
    public string? BatchNo { get; init; }
    public string? Reason { get; init; }
    public string? DecontrolDate { get; init; }
    public string? CertHandoverDate { get; init; }
    public string? Operator { get; init; }
    public string? CreatedAt { get; init; }
    public string Name => $"{Surname}{GivenName}";
}

public record CertIssuance
{
    public long Id { get; init; }
    public long? TravelId { get; init; }
    public long PersonnelFilingId { get; init; }
    public string? HolderName { get; init; }
    public string? IdNumber { get; init; }
    public string? CertTypes { get; init; }
    public string? CertNos { get; init; }
    public string? IssueDate { get; init; }
    public string? Issuer { get; init; }
    public byte[]? SignImage { get; init; }
    public string? ReturnDate { get; init; }
    public byte[]? ReturnSignImage { get; init; }
    public string? ReturnOperator { get; init; }
    public string? Status { get; init; }
    public string? VoidReason { get; init; }
    public string? Remarks { get; init; }
    public string? Operator { get; init; }
    public string? CreatedAt { get; init; }
    public string? WorkUnit { get; init; }          // JOIN 带出
}

public record Attachment
{
    public long Id { get; init; }
    public long TravelId { get; init; }
    public string? FileName { get; init; }
    public string? FilePath { get; init; }
    public string? FileType { get; init; }
    public long FileSize { get; init; }
    public string? UploadedAt { get; init; }
}

public record OperationLog
{
    public long Id { get; init; }
    public string? Operator { get; init; }
    public string? Action { get; init; }
    public string? TargetType { get; init; }
    public long? TargetId { get; init; }
    public string? Detail { get; init; }
    public string? IpAddress { get; init; }
    public string? Snapshot { get; init; }
    public string? CreatedAt { get; init; }
}
